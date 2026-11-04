import { useEffect, useId, useState } from 'react';
import api from '../api';
import './CodeSolutions.css';

function Solution({ solution, official = false }) {
    return <article className="code-solutions__entry">
        <h4>{official ? 'Официальное решение' : 'Решение ученика'} · {solution.author_name}</h4>
        <pre className="code-solutions__code" tabIndex={0} aria-label={official ? 'Код автора' : `Код: ${solution.author_name}`}>
            <code>{solution.code}</code>
        </pre>
    </article>;
}

function SolutionsList({ blockId, id }) {
    const [data, setData] = useState(null);
    const [offset, setOffset] = useState(0);
    const [attempt, setAttempt] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        let cancelled = false;
        api.get(`/blocks/${blockId}/solutions/`, { params: { offset } }).then(response => {
            if (cancelled) return;
            setData(previous => ({ ...response.data,
                results: offset === 0 ? response.data.results : [...previous.results, ...response.data.results],
            }));
        }).catch(err => {
            if (!cancelled) setError(err.response?.data?.detail || 'Не удалось загрузить решения. Попробуйте ещё раз.');
        }).finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [blockId, offset, attempt]);

    return <section id={id} className="code-solutions__list" aria-label="Другие решения">
        {data?.official_solution && <Solution solution={data.official_solution} official />}
        {data?.results.map(solution => <Solution key={solution.id} solution={solution} />)}
        {loading && <p role="status">Загружаем решения…</p>}
        {error && <p className="notice notice-danger" role="alert">{error}{' '}
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => {
                setLoading(true); setError(''); setAttempt(value => value + 1);
            }}>Повторить</button>
        </p>}
        {!loading && !error && data && !data.official_solution && data.results.length === 0 &&
            <p>Других решений пока нет.</p>}
        {data?.next_offset != null && <button type="button" className="btn btn-secondary btn-sm"
            disabled={loading || !!error} onClick={() => {
                setLoading(true); setError(''); setOffset(data.next_offset);
            }}>Показать ещё решения</button>}
    </section>;
}

export default function CodeSolutions({ blockId, unlocked }) {
    const [open, setOpen] = useState(false);
    const id = useId();
    return <div className="code-solutions">
        <button type="button" className="btn btn-secondary" disabled={!unlocked}
            title={unlocked ? undefined : 'Сначала решите задачу'}
            aria-expanded={open && unlocked} aria-controls={open && unlocked ? id : undefined}
            onClick={() => setOpen(value => !value)}>
            {open && unlocked ? 'Скрыть другие решения' : 'Посмотреть другие решения'}
        </button>
        {open && unlocked && <SolutionsList blockId={blockId} id={id} />}
    </div>;
}
