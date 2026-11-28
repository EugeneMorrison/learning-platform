import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';

export default function ReviewModeration({ notification = false }) {
    const [reviews, setReviews] = useState([]);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(null);
    async function load() {
        try { const { data } = await api.get('/reviews/moderation/'); setReviews(data); setError(''); }
        catch { if (!notification) setError('Не удалось загрузить отзывы.'); }
    }
    useEffect(() => {
        load();
        const timer = setInterval(load, 30000);
        return () => clearInterval(timer);
    }, []);
    async function moderate(review, status) {
        setBusy(review.id);
        try {
            await api.post('/reviews/moderation/', { id: review.id, revision: review.revision, status });
            await load();
        } catch { setError('Не удалось сохранить решение. Обновите список: отзыв мог измениться.'); }
        finally { setBusy(null); }
    }
    if (notification) return reviews.length > 0 ? <Link className="btn btn-secondary btn-sm" role="status" to="/dashboard/#course-reviews">
        Новые отзывы: {reviews.length}
    </Link> : null;
    return <section className="section" id="course-reviews">
        <h2>Модерация отзывов</h2>
        {error && <p role="alert">{error} <button onClick={load}>Обновить</button></p>}
        {!reviews.length && !error && <p className="muted">Нет отзывов на модерации.</p>}
        {reviews.map(review => <article className="card" key={review.id}>
            <h3>{review.course_title}</h3>
            <p>{review.username} · {review.rating} / 5 ★</p>
            <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{review.text || 'Без письменного отзыва'}</p>
            <button className="btn btn-primary" disabled={busy !== null} onClick={() => moderate(review, 'approved')}>Одобрить</button>{' '}
            <button className="btn btn-secondary" disabled={busy !== null} onClick={() => moderate(review, 'rejected')}>Отклонить</button>
        </article>)}
    </section>;
}
