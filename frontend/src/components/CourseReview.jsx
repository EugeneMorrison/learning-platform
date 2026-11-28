import { useEffect, useState } from 'react';
import api from '../api';

const statuses = { pending: 'На модерации', approved: 'Опубликован', rejected: 'Отклонён — вы можете изменить отзыв и отправить его снова.' };

export default function CourseReview({ courseId, refreshKey = 0, congratulations = false }) {
    const [data, setData] = useState(null);
    const [rating, setRating] = useState('');
    const [text, setText] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        let active = true;
        api.get(`/courses/${courseId}/my-review/`).then(({ data }) => {
            if (!active) return;
            setData(data); setRating(data.review?.rating || ''); setText(data.review?.text || ''); setError('');
        }).catch(() => { if (active) setError('Не удалось загрузить отзыв.'); });
        return () => { active = false; };
    }, [courseId, refreshKey, retry]);
    async function submit(event) {
        event.preventDefault(); setBusy(true); setError('');
        try {
            const response = await api.put(`/courses/${courseId}/my-review/`, { rating: Number(rating), text });
            setData(prev => ({ ...prev, review: response.data }));
            window.dispatchEvent(new Event('course-review-changed'));
        } catch { setError('Не удалось отправить отзыв. Проверьте оценку и попробуйте снова.'); }
        finally { setBusy(false); }
    }
    if (!data) return error ? <p role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Повторить</button></p> : null;
    if (!data.eligible && !data.review) return null;
    return <section className="section card" aria-label="Отзыв о курсе">
        {congratulations && data.eligible && <h2>Поздравляем! Вы успешно завершили курс!</h2>}
        <h3>{data.review ? 'Ваш отзыв о курсе' : 'Оцените курс'}</h3>
        {data.review && <p role="status">{statuses[data.review.status]}</p>}
        {data.eligible && <form onSubmit={submit}>
            <fieldset disabled={busy}>
                <legend>Оценка — обязательно</legend>
                {[1, 2, 3, 4, 5].map(value => <label key={value} style={{ display: 'inline-block', padding: '0.5rem' }}>
                    <input type="radio" name={`rating-${courseId}`} required value={value} checked={Number(rating) === value}
                        onChange={() => setRating(value)} /> {value} ★
                </label>)}
                <label style={{ display: 'block' }}>Отзыв — необязательно
                    <textarea className="input" maxLength={5000} value={text} onChange={e => setText(e.target.value)} />
                </label>
                <p className="muted">Новые и изменённые отзывы публикуются после модерации.</p>
                <button className="btn btn-primary" disabled={!rating} type="submit">{busy ? 'Отправка…' : 'Отправить на модерацию'}</button>
            </fieldset>
        </form>}
        {error && <p role="alert">{error}</p>}
    </section>;
}
