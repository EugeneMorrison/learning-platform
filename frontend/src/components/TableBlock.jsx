import { useState } from 'react';
import api from '../api';
import { changeCell, restoreTable, tableDisplay } from '../lib/tableTask';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';
import { renderMath } from '../lib/contentMath';
import { DiscussionBadge } from './DiscussionPanel';
import TableGrid from './TableGrid';
import './blocks.css';

export default function TableBlock({ content, blockId, tableRevision, savedProgress, number, onSubmitted, onAsk, discussion }) {
    // Author and student responses share rows/columns. Only the author response
    // contains correct_cells; it is never read for grading or display here.
    const [display, setDisplay] = useState(() => restoreTable(content, savedProgress, tableRevision));
    const [checking, setChecking] = useState(false);
    const [error, setError] = useState('');
    const result = display.result;
    const locked = checking || result?.correct === true;
    const ready = display.multiple_answers || display.rows.every(row => display.selected[row.id]?.length === 1);

    function select(row, column, checked) {
        if (locked) return;
        setDisplay(current => ({ ...current, result: null,
            selected: changeCell(current.selected, row, column, current.multiple_answers, checked) }));
        setError('');
    }

    async function submit() {
        if (locked || !ready) return;
        setChecking(true);
        setError('');
        try {
            const { data } = await api.post('/progress/submit/', {
                block: blockId, answer: { selected: display.selected,
                    row_order: display.rows.map(row => row.id), column_order: display.columns.map(column => column.id),
                    table_revision: tableRevision },
            });
            setDisplay(current => ({ ...current, result: { correct: data.is_correct === true, comment: data.feedback?.comment } }));
            onSubmitted?.(data);
        } catch (err) {
            setError(err.response?.data?.detail || 'Не удалось проверить таблицу. Попробуйте ещё раз.');
        } finally {
            setChecking(false);
        }
    }

    function practice() {
        setDisplay(tableDisplay(content));
        setError('');
    }

    return <div className={`lesson-block${result?.correct ? ' lesson-block--solved' : ''}`}>
        <div className="lesson-block__head">
            <span className="lesson-block__badge">Таблица{number ? ` ${number}` : ''}</span>
            {result?.correct && <span className="lesson-block__solved">✓ Решено</span>}
            {onAsk && <button type="button" className="lesson-block__ask" onClick={() => onAsk()}>Задать вопрос</button>}
            <DiscussionBadge blockId={blockId} discussion={discussion} />
        </div>
        <div className="text-content lesson-block__prompt" dangerouslySetInnerHTML={{
            __html: wrapTables(wrapImages(renderMath(highlightPreBlocks(display.prompt)))),
        }} />
        <p className="lesson-block__label">{display.multiple_answers ? 'В каждой строке можно выбрать несколько вариантов.' : 'Выберите один вариант в каждой строке.'}
            {display.any_answer_correct && ' Это опрос: любой ответ засчитывается.'}</p>
        <TableGrid rows={display.rows} columns={display.columns} selected={display.selected}
            multiple={display.multiple_answers} namePrefix={`table-${blockId}`} disabled={locked} onChange={select} />
        {error && <p className="check-error" role="alert">{error}</p>}
        {result && <div role="status" className={`verdict ${result.correct ? 'verdict--success' : 'verdict--danger'}`}>
            {result.correct ? '✅ Верно!' : '❌ Неверно! Исправьте отмеченные ячейки и отправьте ответ ещё раз.'}
            {result.comment && <span className="verdict__detail"> {result.comment}</span>}
        </div>}
        <div className="lesson-block__actions">
            <div className="lesson-block__actions-start">
                <button className="lesson-block__text-btn" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>↑ Вернуться к теории</button>
            </div>
            <div className="lesson-block__actions-end">{result?.correct
                ? <button className="btn btn-secondary" onClick={practice}>Решить снова</button>
                : <button className="btn btn-primary" disabled={checking || !ready} onClick={submit}>{checking ? 'Проверяем…' : 'Проверить'}</button>}
            </div>
        </div>
    </div>;
}
