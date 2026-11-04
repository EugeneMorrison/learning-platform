import { useEffect, useState } from 'react';
import api from '../api';

export default function MoveBlockControl({ courseId, lessonId, disabled, onMove }) {
    const [open, setOpen] = useState(false);
    const [lessons, setLessons] = useState([]);
    const [destination, setDestination] = useState('');
    const [loading, setLoading] = useState(false);
    const [moving, setMoving] = useState(false);
    const [error, setError] = useState('');
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        if (!open) return undefined;
        let active = true;
        setLoading(true);
        setError('');
        api.get('/lessons/outline/', { params: { course: courseId } }).then(({ data }) => {
            if (active) setLessons(data.filter(lesson => lesson.id !== lessonId));
        }).catch(() => {
            if (active) setError('Не удалось загрузить уроки. Попробуйте ещё раз.');
        }).finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [open, courseId, lessonId, attempt]);

    async function submit(event) {
        event.preventDefault();
        const lesson = lessons.find(row => row.id === destination);
        if (!lesson || moving || disabled) return;
        setMoving(true);
        setError('');
        try {
            await onMove(lesson);
            setOpen(false);
        } catch (err) {
            setError(err.response?.data?.detail || err.message || 'Не удалось перенести блок. Попробуйте ещё раз.');
        } finally {
            setMoving(false);
        }
    }

    if (!open) return <button type="button" className="btn btn-secondary btn-sm" disabled={disabled}
        title={disabled ? 'Сохраните изменения блока перед переносом.' : 'Переместить этот блок в другой урок курса.'}
        onClick={() => { setDestination(''); setOpen(true); }}>↗ В другой урок</button>;
    return <form onSubmit={submit} aria-label="Перенос блока в другой урок" style={{ flexBasis: '100%' }}>
        <p>Блок будет перемещён в конец выбранного урока. Ответы учащихся и обсуждения сохранятся.</p>
        {loading ? <p role="status">Загрузка уроков…</p> : <>
            {lessons.length > 0 ? <label>Урок назначения
                <select className="input" aria-label="Урок назначения" value={destination} disabled={moving || disabled}
                    onChange={event => setDestination(event.target.value)}>
                    <option value="">Выберите урок</option>
                    {lessons.map(lesson => <option key={lesson.id} value={lesson.id}>{lesson.position}. {lesson.title}</option>)}
                </select>
            </label> : !error && <p>В этом курсе пока нет других уроков.</p>}
        </>}
        {error && <p className="notice notice-danger" role="alert">{error}
            {lessons.length === 0 && <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt(value => value + 1)}>Повторить загрузку</button>}
        </p>}
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button type="submit" className="btn btn-primary btn-sm" disabled={loading || !destination || disabled || moving}>
                {moving ? 'Переносим…' : 'Переместить'}</button>
            <button type="button" className="btn btn-secondary btn-sm" disabled={moving} onClick={() => setOpen(false)}>Отмена</button>
        </div>
    </form>;
}
