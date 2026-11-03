import RichTextEditor from './RichTextEditor';
import DragHandle from './DragHandle';
import SortItem from './SortItem';
import { useDragReorder } from '../lib/useDragReorder';
import './sorting.css';
import './matching.css';

export default function MatchFields({ content, setContent }) {
    const pairs = content.pairs || [];
    function move(id, position) {
        setContent(current => {
            const rows = [...current.pairs];
            const from = rows.findIndex(row => row.left.id === id);
            if (from < 0 || position < 1 || position > rows.length) return current;
            const [row] = rows.splice(from, 1);
            rows.splice(position - 1, 0, row);
            return { ...current, pairs: rows };
        });
    }
    const drag = useDragReorder({ ids: pairs.map(row => row.left.id), disabled: false, onMove: move });
    return <>
        <label>Условие задачи</label>
        <RichTextEditor value={content.prompt || ''} onChange={prompt => setContent(c => ({ ...c, prompt }))}
            placeholder="Опишите, какие элементы нужно сопоставить." />
        <p>В каждой строке укажите правильную пару. Если у элемента нет пары, оставьте ячейку напротив пустой. Добавьте минимум две строки; полностью пустые строки не допускаются.</p>
        <ol className="match-list match-editor" aria-label="Правильные пары">
            {pairs.map((pair, index) => <li key={pair.left.id} {...drag.getItemProps(pair.left.id)}>
                <div className="match-editor__row">
                    <DragHandle {...drag.getHandleProps(pair.left.id)} />
                    <div className="match-row">
                        {['left', 'right'].map(side => <div className="match-cell" key={side}>
                            <div className="sort-editor__item">
                                <label htmlFor={`match-${pair[side].id}`}>{side === 'left' ? 'Первый' : 'Второй'} столбец · {index + 1}</label>
                                <textarea id={`match-${pair[side].id}`} aria-label={`Строка ${index + 1}, ${side === 'left' ? 'первый' : 'второй'} столбец`}
                                    value={pair[side].text} placeholder="Пусто — без пары"
                                    onChange={event => setContent(c => ({ ...c, pairs: c.pairs.map(row => row.left.id === pair.left.id
                                        ? { ...row, [side]: { ...row[side], text: event.target.value } } : row) }))} />
                                {content.html && <div className="sort-editor__preview"><SortItem text={pair[side].text} html /></div>}
                            </div>
                        </div>)}
                    </div>
                    <div className="sort-item__arrows">
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Пара ${index + 1}: вверх`} disabled={index === 0} onClick={() => move(pair.left.id, index)}>↑</button>
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Пара ${index + 1}: вниз`} disabled={index === pairs.length - 1} onClick={() => move(pair.left.id, index + 2)}>↓</button>
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Удалить пару ${index + 1}`}
                            onClick={() => setContent(c => ({ ...c, pairs: c.pairs.filter(row => row.left.id !== pair.left.id) }))}>✕</button>
                    </div>
                </div>
            </li>)}
        </ol>
        <button type="button" className="btn btn-secondary" onClick={() => setContent(c => ({ ...c,
            pairs: [...c.pairs, { left: { id: crypto.randomUUID(), text: '' }, right: { id: crypto.randomUUID(), text: '' } }],
        }))}>+ Добавить пару</button>
        <label className="match-setting"><input type="checkbox" checked={content.keep_left_order === true}
            onChange={event => setContent(c => ({ ...c, keep_left_order: event.target.checked }))} /> Не перемешивать первый столбец (второй перемешивается всегда)</label>
        <label className="match-setting"><input type="checkbox" checked={content.html === true}
            onChange={event => setContent(c => ({ ...c, html: event.target.checked }))} /> В тексте элементов есть HTML-теги</label>
        {content.html && <p>Доступны: br, b, i, strong, em, strike, h1–h3, ol, li, ul, blockquote, code, abbr (title).</p>}
        {[['feedback_correct', 'Комментарий при верном ответе'], ['feedback_incorrect', 'Комментарий при неверном ответе']].map(([field, label]) =>
            <label key={field} className="match-setting">{label}
                <textarea className="match-comment" value={content[field] || ''}
                    onChange={event => setContent(c => ({ ...c, [field]: event.target.value }))} placeholder="Необязательно" />
            </label>)}
    </>;
}
