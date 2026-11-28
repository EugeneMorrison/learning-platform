import { useEffect, useState } from 'react';
import api from '../api';

export default function CourseRecommendationsEditor({ courseId, value, onSaved }) {
    const [courses, setCourses] = useState(null);
    const [selected, setSelected] = useState(value);
    const [error, setError] = useState('');
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);

    async function load() {
        setError('');
        try {
            const { data } = await api.get('/courses/');
            setCourses(data.filter(course => course.id !== courseId));
        } catch {
            setError('Не удалось загрузить список курсов.');
        }
    }
    useEffect(() => { load(); }, [courseId]);

    async function save(event) {
        event.preventDefault();
        setSaving(true);
        setError('');
        setSaved(false);
        try {
            const { data } = await api.patch(`/courses/${courseId}/`, { recommended_courses: selected });
            setSelected(data.recommended_courses);
            onSaved(data.recommended_courses);
            setSaved(true);
        } catch {
            setError('Не удалось сохранить рекомендации. Попробуйте ещё раз.');
        } finally {
            setSaving(false);
        }
    }

    return <details className="course-recommendations">
        <summary>Рекомендации после завершения курса</summary>
        <p className="muted">Выберите следующие курсы. Они появятся в рекомендациях после решения всех заданий этого курса.</p>
        {!courses ? <>{error ? <div role="alert">{error} <button className="btn btn-secondary" onClick={load}>Повторить</button></div>
            : <p role="status">Загрузка курсов...</p>}</> : <form onSubmit={save}>
            <fieldset disabled={saving}>
                <legend>Следующие курсы</legend>
                {courses.length === 0 && <p className="muted">Других доступных курсов пока нет.</p>}
                {selected.filter(id => !courses.some(course => course.id === id)).map(id => <label key={id} className="course-recommendations__option">
                    <input type="checkbox" checked onChange={() => {
                        setSaved(false);
                        setSelected(prev => prev.filter(value => value !== id));
                    }} /> Недоступный курс — снимите отметку, чтобы удалить рекомендацию
                </label>)}
                {courses.map(course => <label key={course.id} className="course-recommendations__option">
                    <input type="checkbox" checked={selected.includes(course.id)} onChange={event => {
                        setSaved(false);
                        setSelected(prev => event.target.checked ? [...prev, course.id] : prev.filter(id => id !== course.id));
                    }} /> {course.title}{!course.is_published && ' (не опубликован)'}
                </label>)}
                <button className="btn btn-secondary" type="submit">{saving ? 'Сохранение…' : 'Сохранить рекомендации'}</button>
            </fieldset>
            {error && <p role="alert">{error}</p>}
            {saved && <p role="status">Рекомендации сохранены.</p>}
        </form>}
    </details>;
}
