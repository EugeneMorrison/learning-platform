import RichTextEditor from './RichTextEditor';
import TableGrid from './TableGrid';
import { changeCell } from '../lib/tableTask';
import { moveItem } from '../lib/sorting';

export default function TableFields({ uid, content, setContent }) {
    function add(axis) {
        const id = crypto.randomUUID();
        setContent(c => ({ ...c, [axis]: [...c[axis], { id, text: '' }],
            correct_cells: axis === 'rows' ? { ...c.correct_cells, [id]: [] } : c.correct_cells }));
    }
    function remove(axis, id) {
        setContent(c => ({ ...c, [axis]: c[axis].filter(item => item.id !== id),
            correct_cells: Object.fromEntries(Object.entries(c.correct_cells || {})
                .filter(([row]) => axis !== 'rows' || row !== id)
                .map(([row, cells]) => [row, axis === 'columns' ? cells.filter(cell => cell !== id) : cells])) }));
    }
    function mode(multiple_answers) {
        setContent(c => ({ ...c, multiple_answers, correct_cells: Object.fromEntries(
            Object.entries(c.correct_cells || {}).map(([row, cells]) => [row, multiple_answers ? cells : cells.slice(0, 1)])) }));
    }
    return <>
        <label>Условие задачи</label>
        <RichTextEditor value={content.prompt || ''} onChange={prompt => setContent(c => ({ ...c, prompt }))}
            placeholder="Опишите, какие ячейки нужно выбрать." />
        <fieldset className="table-fields__mode"><legend>Сколько вариантов можно выбрать в каждой строке</legend>
            <label><input type="radio" name={`${uid}-mode`} checked={!content.multiple_answers} onChange={() => mode(false)} /> Один</label>
            <label><input type="radio" name={`${uid}-mode`} checked={content.multiple_answers === true} onChange={() => mode(true)} /> Несколько</label>
        </fieldset>
        <div className="table-fields__axes">{[['rows', 'Строки', 'строки', 'строку'], ['columns', 'Столбцы', 'столбца', 'столбец']].map(([axis, title, genitive, singular]) =>
            <section key={axis}><h4>{title}</h4>
                {content[axis].map((item, index) => <div key={item.id} className="table-fields__item">
                    <input type="text" aria-label={`Название ${genitive} ${index + 1}`} value={item.text}
                        onChange={event => setContent(c => ({ ...c, [axis]: c[axis].map(row => row.id === item.id ? { ...row, text: event.target.value } : row) }))} />
                    <button type="button" className="btn btn-secondary btn-sm" aria-label={`${title} ${index + 1}: вверх`} disabled={index === 0}
                        onClick={() => setContent(c => ({ ...c, [axis]: moveItem(c[axis], item.id, index) }))}>↑</button>
                    <button type="button" className="btn btn-secondary btn-sm" aria-label={`${title} ${index + 1}: вниз`} disabled={index === content[axis].length - 1}
                        onClick={() => setContent(c => ({ ...c, [axis]: moveItem(c[axis], item.id, index + 2) }))}>↓</button>
                    <button type="button" className="btn btn-secondary btn-sm" aria-label={`Удалить ${singular} ${index + 1}`} onClick={() => remove(axis, item.id)}>✕</button>
                </div>)}
                <button type="button" className="btn btn-secondary" onClick={() => add(axis)}>+ Добавить {singular}</button>
            </section>)}</div>
        {[['shuffle_rows', 'Перемешивать порядок строк'], ['shuffle_columns', 'Перемешивать порядок столбцов'],
            ['any_answer_correct', 'Любой ответ верный (опрос)']].map(([field, label]) =>
            <label key={field} className="table-fields__setting"><input type="checkbox" checked={content[field] === true}
                onChange={event => setContent(c => ({ ...c, [field]: event.target.checked }))} /> {label}</label>)}
        <h4>{content.any_answer_correct ? 'Предпросмотр опроса' : 'Правильные ячейки'}</h4>
        <p>{content.any_answer_correct ? 'Любой допустимый ответ будет засчитан. Отмечать правильные ячейки не требуется.'
            : content.multiple_answers ? 'Отметьте все правильные ячейки. В строке может не быть правильных вариантов.' : 'Отметьте один правильный вариант в каждой строке.'}</p>
        <TableGrid rows={content.rows} columns={content.columns} selected={content.correct_cells}
            multiple={content.multiple_answers} namePrefix={`table-editor-${uid}`} disabled={content.any_answer_correct}
            onChange={(row, column, checked) => setContent(c => ({ ...c,
                correct_cells: changeCell(c.correct_cells || {}, row, column, c.multiple_answers, checked) }))}
            label="Правильные ячейки таблицы" />
        {[['feedback_correct', 'Комментарий при верном ответе'], ['feedback_incorrect', 'Комментарий при неверном ответе']].map(([field, label]) =>
            <label key={field} className="table-fields__setting">{label}
                <textarea className="table-fields__comment" value={content[field] || ''} placeholder="Необязательно"
                    onChange={event => setContent(c => ({ ...c, [field]: event.target.value }))} />
            </label>)}
    </>;
}
