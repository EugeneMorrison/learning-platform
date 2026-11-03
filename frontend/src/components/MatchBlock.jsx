import { useState } from 'react';
import api from '../api';
import { useDragReorder } from '../lib/useDragReorder';
import { moveItem } from '../lib/sorting';
import { matchingDisplay, restoreMatching } from '../lib/matching';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';
import { renderMath } from '../lib/contentMath';
import { DiscussionBadge } from './DiscussionPanel';
import DragHandle from './DragHandle';
import { MatchItem } from './MatchPairs';
import './blocks.css';

export default function MatchBlock({ content, blockId, matchRevision, savedProgress, number, onSubmitted, onAsk, discussion }) {
    const [display, setDisplay] = useState(() => restoreMatching(content, savedProgress));
    const [result, setResult] = useState(savedProgress ? {
        correct: savedProgress.is_correct === true, comment: savedProgress.feedback?.comment,
    } : null);
    const [checking, setChecking] = useState(false);
    const [error, setError] = useState('');
    const locked = checking || result !== null;
    const move = (id, position) => setDisplay(current => ({ ...current, right: moveItem(current.right, id, position) }));
    const drag = useDragReorder({ ids: display.right.map(item => item.id), disabled: locked, onMove: move });

    async function submit() {
        if (locked) return;
        setChecking(true);
        setError('');
        try {
            const { data } = await api.post('/progress/submit/', {
                block: blockId,
                answer: { left_order: display.left.map(item => item.id),
                    right_order: display.right.map(item => item.id), match_revision: matchRevision },
            });
            setResult({ correct: data.is_correct === true, comment: data.feedback?.comment });
            onSubmitted?.(data);
        } catch (err) {
            setError(err.response?.data?.detail || 'Не удалось проверить сопоставление. Попробуйте ещё раз.');
        } finally {
            setChecking(false);
        }
    }

    function retry() {
        setDisplay(matchingDisplay(content));
        setResult(null);
        setError('');
    }

    return <div className={`lesson-block${result?.correct ? ' lesson-block--solved' : ''}`}>
        <div className="lesson-block__head">
            <span className="lesson-block__badge">Сопоставление{number ? ` ${number}` : ''}</span>
            {result?.correct && <span className="lesson-block__solved">✓ Решено</span>}
            {onAsk && <button type="button" className="lesson-block__ask" onClick={() => onAsk()}>Задать вопрос</button>}
            <DiscussionBadge blockId={blockId} discussion={discussion} />
        </div>
        <div className="text-content lesson-block__prompt" dangerouslySetInnerHTML={{
            __html: wrapTables(wrapImages(renderMath(highlightPreBlocks(content.prompt)))),
        }} />
        <p className="lesson-block__label">Сопоставьте элементы в каждой строке. Перетаскивайте правые элементы или используйте стрелки. Пустая ячейка означает «Без пары».</p>
        <ol className="match-list" aria-label="Сопоставление двух списков">
            {display.left.map((left, index) => {
                const right = display.right[index];
                return <li key={left.id} className="match-row">
                    <div className="match-cell match-cell--left"><MatchItem item={left} html={display.html} /></div>
                    <div {...drag.getItemProps(right.id)}>
                        <div className="match-cell">
                            <DragHandle {...drag.getHandleProps(right.id)} />
                            <MatchItem item={right} html={display.html} />
                            <div className="sort-item__arrows">
                                <button type="button" className="btn btn-secondary btn-sm" aria-label={`Правый элемент ${index + 1}: вверх`}
                                    disabled={locked || index === 0} onClick={() => move(right.id, index)}>↑</button>
                                <button type="button" className="btn btn-secondary btn-sm" aria-label={`Правый элемент ${index + 1}: вниз`}
                                    disabled={locked || index === display.right.length - 1} onClick={() => move(right.id, index + 2)}>↓</button>
                            </div>
                        </div>
                    </div>
                </li>;
            })}
        </ol>
        {error && <p className="check-error" role="alert">{error}</p>}
        {result && <div role="status" className={`verdict ${result.correct ? 'verdict--success' : 'verdict--danger'}`}>
            {result.correct ? '✅ Верно!' : '❌ Неверно! Проверьте пары и попробуйте ещё раз.'}
            {result.comment && <span className="verdict__detail"> {result.comment}</span>}
        </div>}
        <div className="lesson-block__actions">
            <div className="lesson-block__actions-start">
                <button className="lesson-block__text-btn" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>↑ Вернуться к теории</button>
            </div>
            <div className="lesson-block__actions-end">{result
                ? <button className="btn btn-secondary" onClick={retry}>{result.correct ? 'Решить снова' : 'Попробовать снова'}</button>
                : <button className="btn btn-primary" disabled={checking} onClick={submit}>{checking ? 'Проверяем…' : 'Проверить'}</button>}
            </div>
        </div>
    </div>;
}
