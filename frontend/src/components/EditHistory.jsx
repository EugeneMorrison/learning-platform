import { useEffect, useRef, useState } from 'react';
import api from '../api';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';
import { renderMath } from '../lib/contentMath';
import './EditHistory.css';

const ACTIONS = { created: 'Добавлено', updated: 'Изменено', deleted: 'Удалено', reordered: 'Изменён порядок',
    duplicated: 'Скопировано', restored: 'Восстановлена версия' };
const KINDS = { course: 'Курс', lesson: 'Урок', block: 'Блок' };
const TYPES = { TEXT: 'Теория', QUIZ: 'Тест', CODE: 'Задача с кодом', FILL: 'Пропуски', SORT: 'Сортировка', MATCH: 'Сопоставление', TABLE: 'Таблица' };
const FIELDS = { title: 'Название', description: 'Описание', level: 'Уровень', is_published: 'Опубликован',
    price: 'Цена', cover: 'Обложка', type: 'Тип блока', order_index: 'Порядок', content: 'Содержимое', order: 'Порядок',
    blocks: 'Блоки урока', course_id: 'Курс', lesson_id: 'Урок', lesson_number: 'Номер урока' };
const date = value => new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
const errorText = error => error.response?.data?.detail || 'Не удалось загрузить историю. Попробуйте ещё раз.';

function blockLabel(value) {
    const type = value.type || value.block_type;
    return `${TYPES[type] || 'Блок'}${value.block_number ? ` ${value.block_number}` : ''}${value.number_is_current ? ' (номер сейчас)' : ''}`;
}

function lessonLabel(entry, version) {
    if (!entry.lesson_title) return null;
    const number = version?.lesson_number ?? entry.lesson_number;
    const current = version?.lesson_number_is_current ?? entry.lesson_number_is_current;
    return `Урок${number ? ` ${number}` : ''}: «${entry.lesson_title}»${current ? ' (номер сейчас)' : ''}`;
}

function Snapshot({ value, targetId }) {
    if (!value) return <p className="muted">В этой версии объекта ещё нет или он уже удалён.</p>;
    if (value.order) return <ol className="edit-history__order">{value.order.map(item => (
        <li key={item.id} className={item.id === targetId ? 'edit-history__moved' : undefined}>
            {item.title ? `${item.number ? `Урок ${item.number}: ` : ''}${item.title}`
                : blockLabel({ type: item.type, block_number: item.number })} <small>({item.id.slice(0, 8)})</small>
        </li>
    ))}</ol>;
    const mainField = value.type === 'TEXT' ? 'html' : value.type === 'QUIZ' ? 'question' : 'prompt';
    const html = value.content?.[mainField];
    const settings = value.content && Object.fromEntries(Object.entries(value.content).filter(([key]) => key !== mainField));
    return (
        <div>
            {value.type && <p><strong>{blockLabel(value)}</strong></p>}
            {html && <div className="text-content" dangerouslySetInnerHTML={{ __html: wrapTables(wrapImages(renderMath(highlightPreBlocks(html)))) }} />}
            {settings && Object.keys(settings).length > 0 && <details className="edit-history__settings" open>
                <summary>Настройки и ответы</summary><pre>{JSON.stringify(settings, null, 2)}</pre>
            </details>}
            {!value.content && <dl className="edit-history__fields">{Object.entries(value).filter(([key]) => key !== 'id' && !key.endsWith('_is_current')).map(([key, field]) => (
                <div key={key}><dt>{FIELDS[key] || key}</dt><dd>{typeof field === 'object' ? <pre>{JSON.stringify(field, null, 2)}</pre>
                    : typeof field === 'boolean' ? (field ? 'Да' : 'Нет') : String(field ?? '—')}</dd></div>
            ))}</dl>}
        </div>
    );
}

export function EditHistoryDialog({ courseId, lessonId, blockId, title, onClose, onRestore }) {
    const [entries, setEntries] = useState([]);
    const [cursor, setCursor] = useState(null);
    const [selected, setSelected] = useState(null);
    const [detail, setDetail] = useState(null);
    const [side, setSide] = useState('after');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [detailError, setDetailError] = useState('');
    const [restoring, setRestoring] = useState(false);
    const [attempt, setAttempt] = useState(0);
    const [kind, setKind] = useState('');
    const [action, setAction] = useState('');
    const dialogRef = useRef(null);
    const requestRef = useRef(0);
    const mountedRef = useRef(true);
    const scope = { ...(lessonId ? { lesson: lessonId } : {}), ...(blockId ? { block: blockId } : {}),
        ...(kind ? { kind } : {}), ...(action ? { action } : {}) };

    useEffect(() => {
        mountedRef.current = true;
        const opener = document.activeElement;
        dialogRef.current?.focus();
        document.documentElement.classList.add('edit-history-open');
        return () => {
            mountedRef.current = false;
            document.documentElement.classList.remove('edit-history-open');
            if (opener?.isConnected) opener.focus();
        };
    }, []);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError('');
        setEntries([]);
        setCursor(null);
        api.get(`/courses/${courseId}/history/`, { params: scope }).then(res => {
            if (cancelled) return;
            setEntries(res.data.results);
            setCursor(res.data.next_cursor);
            setSelected(res.data.results[0]?.id ?? null);
        }).catch(err => { if (!cancelled) setError(errorText(err)); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
        // Scope is represented by the primitive dependencies below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [courseId, lessonId, blockId, attempt, kind, action]);

    useEffect(() => {
        if (!selected) return undefined;
        let cancelled = false;
        setDetail(null);
        setDetailError('');
        api.get(`/courses/${courseId}/history/`, { params: { ...scope, event: selected } }).then(res => {
            if (cancelled) return;
            setDetail(res.data);
            setSide(res.data.after ? 'after' : 'before');
        }).catch(err => { if (!cancelled) setDetailError(errorText(err)); });
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [selected, courseId, lessonId, blockId, attempt, kind, action]);

    async function more() {
        const request = ++requestRef.current;
        setLoading(true);
        setError('');
        try {
            const res = await api.get(`/courses/${courseId}/history/`, { params: { ...scope, before: cursor } });
            if (!mountedRef.current || request !== requestRef.current) return;
            setEntries(prev => [...prev, ...res.data.results]);
            setCursor(res.data.next_cursor);
        } catch (err) { if (mountedRef.current && request === requestRef.current) setError(errorText(err)); }
        finally { if (mountedRef.current && request === requestRef.current) setLoading(false); }
    }

    async function restore() {
        setRestoring(true);
        setDetailError('');
        try {
            if (await onRestore(detail.id, side) !== false) onClose();
        } catch (err) { setDetailError(err.response?.data?.detail || 'Не удалось восстановить версию. Попробуйте ещё раз.'); }
        finally { setRestoring(false); }
    }

    function keyDown(event) {
        if (event.key === 'Escape' && !restoring) { event.stopPropagation(); onClose(); }
        if (event.key !== 'Tab') return;
        const items = [...dialogRef.current.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), summary, [tabindex="0"]')];
        const first = items[0];
        const last = items.at(-1);
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
            event.preventDefault(); last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }

    const version = detail?.[side];
    function filter(setter, value) {
        requestRef.current++;
        setSelected(null);
        setDetail(null);
        setDetailError('');
        setter(value);
    }
    return (
        <div className="edit-history-layer" onKeyDown={keyDown}>
            <div className="edit-history__backdrop" aria-hidden="true" onClick={() => { if (!restoring) onClose(); }} />
            <section ref={dialogRef} tabIndex={-1} className="edit-history" role="dialog" aria-modal="true" aria-labelledby="edit-history-title">
                <div className="edit-history__head">
                    <div><h2 id="edit-history-title">История изменений</h2><p>{title}</p></div>
                    <button className="btn btn-secondary btn-sm" onClick={onClose} disabled={restoring} aria-label="Закрыть историю">✕</button>
                </div>
                <div className="edit-history__filters">
                    {!lessonId && !blockId && <label>Объект <select className="input" aria-label="Объект истории" disabled={restoring}
                        value={kind} onChange={event => filter(setKind, event.target.value)}>
                        <option value="">Все</option>{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select></label>}
                    <label>Действие <select className="input" aria-label="Действие в истории" disabled={restoring}
                        value={action} onChange={event => filter(setAction, event.target.value)}>
                        <option value="">Все изменения</option>{Object.entries(ACTIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select></label>
                </div>
                <div className="edit-history__body">
                    <div className="edit-history__list">
                        {entries.map(entry => <button type="button" key={entry.id} className={selected === entry.id ? 'edit-history__entry edit-history__entry--selected' : 'edit-history__entry'}
                            onClick={() => setSelected(entry.id)} disabled={restoring} aria-pressed={selected === entry.id}>
                            <time dateTime={entry.created_at}>{date(entry.created_at)}</time>
                            <strong>{ACTIONS[entry.action]} · {entry.kind === 'block' ? blockLabel(entry) : KINDS[entry.kind]}</strong>
                            {entry.lesson_title && <span className="edit-history__location">{lessonLabel(entry)}</span>}
                            <span>{entry.target_label}</span><span>{entry.actor_name}</span>
                        </button>)}
                        {loading && <p role="status">Загружаем историю…</p>}
                        {!loading && !error && entries.length === 0 && <p>{kind || action ? 'По этим фильтрам изменений нет.' : 'Изменений пока нет. История сохраняется с момента включения этой функции.'}</p>}
                        {error && <p className="notice notice-danger" role="alert">{error} <button className="btn btn-secondary btn-sm" onClick={() => setAttempt(prev => prev + 1)}>Повторить</button></p>}
                        {cursor && <button className="btn btn-secondary btn-sm" disabled={loading || restoring} onClick={more}>Показать ещё</button>}
                    </div>
                    <div className="edit-history__preview">
                        {selected && !detail && !detailError && <p role="status">Загружаем версию…</p>}
                        {detail && <>
                            <p>{ACTIONS[detail.action]} · {date(detail.created_at)} · {detail.actor_name}</p>
                            {detail.lesson_title && <p className="edit-history__location">{lessonLabel(detail, version)}</p>}
                            <p className="muted">{detail.changed_fields.filter(field => field !== 'id').map(field => FIELDS[field] || field).join(', ')}</p>
                            <div className="edit-history__tabs">
                                <button className="btn btn-secondary btn-sm" aria-pressed={side === 'before'} onClick={() => setSide('before')} disabled={restoring}>До изменения</button>
                                <button className="btn btn-secondary btn-sm" aria-pressed={side === 'after'} onClick={() => setSide('after')} disabled={restoring}>После изменения</button>
                            </div>
                            <Snapshot value={version} targetId={detail.target_id} />
                            {onRestore && version?.content && <button className="btn btn-primary edit-history__restore" disabled={restoring}
                                onClick={restore}>{restoring ? 'Восстановление…' : 'Восстановить эту версию'}</button>}
                            {detail.source_id && <p className="muted">Восстановлено из записи №{detail.source_id}.</p>}
                        </>}
                        {detailError && <p className="notice notice-danger" role="alert">{detailError}
                            {!detail && <button className="btn btn-secondary btn-sm" onClick={() => setAttempt(prev => prev + 1)}>Повторить</button>}
                        </p>}
                    </div>
                </div>
            </section>
        </div>
    );
}

function EditHistoryButton(props) {
    const [open, setOpen] = useState(false);
    return <>
        <button type="button" className="btn btn-secondary btn-sm" disabled={props.disabled} onClick={() => setOpen(true)}>История изменений</button>
        {open && <EditHistoryDialog {...props} onClose={() => setOpen(false)} />}
    </>;
}

export default EditHistoryButton;
