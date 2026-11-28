import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import CourseCover from './CourseCover';
import { COURSE_LEVELS, NO_LEVEL_LABEL } from '../lib/courseLevels';

export default function StudentDashboard() {
    const [data, setData] = useState(null);
    const [error, setError] = useState(false);
    const [loading, setLoading] = useState(true);

    async function load() {
        setLoading(true);
        setError(false);
        try {
            const response = await api.get('/dashboard/');
            setData(response.data);
        } catch {
            setError(true);
        } finally {
            setLoading(false);
        }
    }
    useEffect(() => { load(); }, []);

    if (loading) return <p className="page-status">Загрузка курсов...</p>;
    if (error) return <div role="alert"><p>Не удалось загрузить курсы.</p>
        <button className="btn btn-secondary" onClick={load}>Попробовать снова</button></div>;

    return <>
        {[
            ['in_progress', 'Курсы в процессе', 'У вас пока нет курсов в процессе обучения.'],
            ['completed', 'Завершённые курсы', 'Здесь появятся курсы, в которых вы решили не менее 89% заданий.'],
            ['recommended', 'Рекомендуемые курсы', 'Пока нет подходящих рекомендаций. Загляните позже.'],
        ].map(([key, title, empty]) => <section className="section" key={key} aria-labelledby={`dash-${key}`}>
            <div className="section__header"><h2 className="section__title" id={`dash-${key}`}>{title}</h2></div>
            {data[key].length === 0 ? <p className="muted">{empty}</p> : <div className="card-grid">
                {data[key].map(course => <article key={course.id} className="card dash-card">
                    <div className="dash-card__cover"><CourseCover title={course.title} cover={course.cover} /></div>
                    <h3 className="dash-card__title">{course.title}</h3>
                    {key === 'in_progress' && <div className="dash-card__progress">
                        <label htmlFor={`progress-${course.id}`}>Пройдено: {course.completion_percentage}%</label>
                        <progress id={`progress-${course.id}`} max="100" value={course.completion_percentage} />
                    </div>}
                    {key === 'completed' && <span className="pill">✓ Завершён</span>}
                    {key === 'recommended' && <p className="dash-card__meta">Уровень: {
                        COURSE_LEVELS.find(level => level.value === course.level)?.label || NO_LEVEL_LABEL
                    }</p>}
                    <div className="dash-card__actions">
                        {key === 'recommended' ? <>
                            <a className="btn btn-secondary" href={`/course/${course.slug}/`}>Подробнее</a>
                            <strong className="dash-card__price">{Number(course.price) === 0 ? 'Бесплатно'
                                : `${new Intl.NumberFormat('ru-RU').format(Number(course.price))} ₽`}</strong>
                        </> : <Link className="btn btn-primary" to={key === 'in_progress' && course.last_lesson
                            ? `/lesson/${course.last_lesson}/` : `/courses/${course.id}/`}>
                            {key === 'completed' ? 'Повторить курс' : 'Продолжить обучение'}
                        </Link>}
                    </div>
                </article>)}
            </div>}
        </section>)}
    </>;
}
