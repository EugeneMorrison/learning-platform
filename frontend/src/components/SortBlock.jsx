import { useState } from 'react';
import api from '../api';
import { useDragReorder } from '../lib/useDragReorder';
import { moveItem, shuffledItems } from '../lib/sorting';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';
import { renderMath } from '../lib/contentMath';
import { DiscussionBadge } from './DiscussionPanel';
import DragHandle from './DragHandle';
import SortItem from './SortItem';
import './blocks.css';
import './sorting.css';

export default function SortBlock({ content, blockId, sortRevision, savedProgress, number, onSubmitted, onAsk, discussion }) {
    const [items, setItems] = useState(() => savedProgress?.answer?.items || shuffledItems(content.items));
    const [html, setHtml] = useState(savedProgress?.answer?.html ?? content.html);
    const [result, setResult] = useState(savedProgress ? {
        correct: savedProgress.is_correct === true, comment: savedProgress.feedback?.comment,
    } : null);
    const [checking, setChecking] = useState(false);
    const [error, setError] = useState('');
    const locked = checking || result !== null;
    const drag = useDragReorder({ ids: items.map(item => item.id), disabled: locked,
        onMove: (id, position) => setItems(current => moveItem(current, id, position)) });

    async function submit() {
        if (locked) return;
        setChecking(true);
        setError('');
        try {
            const { data } = await api.post('/progress/submit/', {
                block: blockId,
                answer: { order: items.map(item => item.id), sort_revision: sortRevision },
            });
            setResult({ correct: data.is_correct === true, comment: data.feedback?.comment });
            onSubmitted?.(data);
        } catch (err) {
            setError(err.response?.data?.detail || 'Не удалось проверить порядок. Попробуйте ещё раз.');
        } finally {
            setChecking(false);
        }
    }

    function retry() {
        setItems(shuffledItems(content.items));
        setHtml(content.html);
        setResult(null);
        setError('');
    }

    return <div className={`lesson-block${result?.correct ? ' lesson-block--solved' : ''}`}>
        <div className="lesson-block__head">
            <span className="lesson-block__badge">Сортировка{number ? ` ${number}` : ''}</span>
            {result?.correct && <span className="lesson-block__solved">✓ Решено</span>}
            {onAsk && <button type="button" className="lesson-block__ask" onClick={() => onAsk()}>Задать вопрос</button>}
            <DiscussionBadge blockId={blockId} discussion={discussion} />
        </div>
        <div className="text-content lesson-block__prompt" dangerouslySetInnerHTML={{
            __html: wrapTables(wrapImages(renderMath(highlightPreBlocks(content.prompt)))),
        }} />
        <p className="lesson-block__label">Расположите элементы сверху вниз. Перетаскивайте их или используйте стрелки.</p>
        <ol className="sort-list" aria-label="Порядок элементов">
            {items.map((item, index) => <li key={item.id} {...drag.getItemProps(item.id)}>
                <div className="sort-item">
                    <DragHandle {...drag.getHandleProps(item.id)} />
                    <SortItem text={item.text} html={html} />
                    <div className="sort-item__arrows">
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Элемент ${index + 1}: вверх`}
                            disabled={locked || index === 0} onClick={() => setItems(current => moveItem(current, item.id, index))}>↑</button>
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Элемент ${index + 1}: вниз`}
                            disabled={locked || index === items.length - 1} onClick={() => setItems(current => moveItem(current, item.id, index + 2))}>↓</button>
                    </div>
                </div>
            </li>)}
        </ol>
        {error && <p className="check-error" role="alert">{error}</p>}
        {result && <div role="status" className={`verdict ${result.correct ? 'verdict--success' : 'verdict--danger'}`}>
            {result.correct ? '✅ Верно!' : '❌ Неверно! Проверьте порядок и попробуйте ещё раз.'}
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
