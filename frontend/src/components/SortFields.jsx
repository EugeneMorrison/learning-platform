import RichTextEditor from './RichTextEditor';
import AutoResizeTextarea from './AutoResizeTextarea';
import DragHandle from './DragHandle';
import SortItem from './SortItem';
import { useDragReorder } from '../lib/useDragReorder';
import { moveItem } from '../lib/sorting';
import './sorting.css';

export default function SortFields({ content, setContent }) {
    const items = content.items || [];
    const drag = useDragReorder({ ids: items.map(item => item.id), disabled: false,
        onMove: (id, position) => setContent(c => ({ ...c, items: moveItem(c.items, id, position) })) });
    const move = (id, position) => setContent(c => ({ ...c, items: moveItem(c.items, id, position) }));
    return <>
        <label>Условие задачи</label>
        <RichTextEditor value={content.prompt || ''} onChange={prompt => setContent(c => ({ ...c, prompt }))}
            placeholder="Укажите, в каком порядке расположить элементы: например, по возрастанию сверху вниз." />
        <p>Добавьте элементы и расположите их в верном порядке сверху вниз. Укажите требуемый порядок в условии. Ученику элементы будут показаны вперемешку.</p>
        <ol className="sort-list sort-editor" aria-label="Правильный порядок элементов">
            {items.map((item, index) => <li key={item.id} {...drag.getItemProps(item.id)}>
                <div className="sort-item">
                    <DragHandle {...drag.getHandleProps(item.id)} />
                    <div className="sort-editor__item">
                        <AutoResizeTextarea className="input" aria-label={`Элемент ${index + 1}`} value={item.text}
                            onChange={event => setContent(c => ({ ...c, items: c.items.map(row => row.id === item.id ? { ...row, text: event.target.value } : row) }))} />
                        {content.html && <div className="sort-editor__preview"><SortItem text={item.text} html /></div>}
                    </div>
                    <div className="sort-item__arrows">
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Элемент ${index + 1}: вверх`} disabled={index === 0} onClick={() => move(item.id, index)}>↑</button>
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Элемент ${index + 1}: вниз`} disabled={index === items.length - 1} onClick={() => move(item.id, index + 2)}>↓</button>
                        <button type="button" className="btn btn-secondary btn-sm" aria-label={`Удалить элемент ${index + 1}`}
                            onClick={() => setContent(c => ({ ...c, items: c.items.filter(row => row.id !== item.id) }))}>✕</button>
                    </div>
                </div>
            </li>)}
        </ol>
        <button type="button" className="btn btn-secondary" onClick={() => setContent(c => ({ ...c,
            items: [...c.items, { id: crypto.randomUUID(), text: '' }],
        }))}>+ Добавить элемент</button>
        <label style={{ display: 'block', margin: '16px 0' }}><input type="checkbox" checked={content.html === true}
            onChange={event => setContent(c => ({ ...c, html: event.target.checked }))} /> В тексте ответов есть HTML-теги</label>
        {content.html && <p>Доступны: br, b, i, strong, em, strike, h1–h3, ol, li, ul, blockquote, code, abbr (title).</p>}
        {[['feedback_correct', 'Комментарий при верном ответе'], ['feedback_incorrect', 'Комментарий при неверном ответе']].map(([field, label]) =>
            <label key={field} style={{ display: 'block', marginTop: 12 }}>{label}
                <AutoResizeTextarea style={{ display: 'block', width: '100%' }} value={content[field] || ''}
                    onChange={event => setContent(c => ({ ...c, [field]: event.target.value }))} placeholder="Необязательно" />
            </label>)}
    </>;
}
