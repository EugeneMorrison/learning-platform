import { useEffect, useState } from 'react';
import api from '../api';

export default function PublishedReviews({ courseId }) {
    const [data, setData] = useState(null);
    const [error, setError] = useState(false);
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        const refresh = () => setRetry(n => n + 1);
        window.addEventListener('course-review-changed', refresh);
        return () => window.removeEventListener('course-review-changed', refresh);
    }, []);
    useEffect(() => {
        let active = true;
        api.get(`/courses/${courseId}/reviews/`).then(({ data }) => { if (active) { setData(data); setError(false); } })
            .catch(() => { if (active) setError(true); });
        return () => { active = false; };
    }, [courseId, retry]);
    return <section className="section"><h2>Отзывы о курсе</h2>
        {error ? <p role="alert">Не удалось загрузить отзывы. <button onClick={() => setRetry(n => n + 1)}>Повторить</button></p>
            : !data ? <p>Загрузка…</p> : <>
                <p>{data.count ? `Средняя оценка: ${data.average.toFixed(2)} / 5 · Отзывов: ${data.count}` : 'Опубликованных отзывов пока нет.'}</p>
                {data.reviews.map(review => <article key={review.id}>
                    <h3>{review.username} · {review.rating} / 5 ★</h3>
                    <time dateTime={review.published_at}>{new Date(review.published_at).toLocaleDateString('ru-RU')}</time>
                    <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{review.text}</p>
                </article>)}
            </>}
    </section>;
}
