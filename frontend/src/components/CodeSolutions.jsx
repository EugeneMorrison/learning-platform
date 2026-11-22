import { useEffect, useId, useState } from 'react';
import api from '../api';
import './CodeSolutions.css';

function Solution({ solution, official = false }) {
    return <article className="code-solutions__entry">
        <h4>{official ? 'Решение автора' : 'Решение ученика'} · {solution.author_name}</h4>
        <pre className="code-solutions__code" tabIndex={0} aria-label={official ? 'Код автора' : `Код: ${solution.author_name}`}>
            <code>{solution.code}</code>
        </pre>
    </article>;
}

function SolutionsList({ blockId }) {
    const [peersOpen, setPeersOpen] = useState(false);
    const peersId = useId();
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

    return <section className="code-solutions" aria-label="Другие решения">
        {data?.official_solution && <Solution solution={data.official_solution} official />}
        {data && (data.results.length > 0 || data.next_offset != null) && (
            <button type="button" className="tests-toggle" aria-expanded={peersOpen}
                aria-controls={peersId} onClick={() => setPeersOpen(value => !value)}>
                <span aria-hidden="true">{peersOpen ? '▼' : '▶'}</span>
                <span>Решения учеников</span>
            </button>
        )}
        <div id={peersId} hidden={!peersOpen}>
            {peersOpen && data?.results.map(solution => <Solution key={solution.id} solution={solution} />)}
            {data?.next_offset != null && <button type="button" className="btn btn-secondary btn-sm"
                disabled={loading || !!error} onClick={() => {
                    setLoading(true); setError(''); setOffset(data.next_offset);
                }}>Показать ещё решения</button>}
        </div>
        {loading && (offset === 0 || peersOpen) && <p role="status">Загружаем решения…</p>}
        {error && (offset === 0 || peersOpen) && <p className="notice notice-danger" role="alert">{error}{' '}
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => {
                setLoading(true); setError(''); setAttempt(value => value + 1);
            }}>Повторить</button>
        </p>}
        {!loading && !error && data && !data.official_solution && data.results.length === 0 && data.next_offset == null &&
            <p>Других решений пока нет.</p>}
    </section>;
}

export default function CodeSolutions({ blockId, unlocked }) {
    if (unlocked) return <SolutionsList key={blockId} blockId={blockId} />;
    return <div className="code-solutions">
        <button type="button" className="btn btn-secondary" disabled title="Сначала решите задачу">
            Посмотреть другие решения
        </button>
    </div>;
}
