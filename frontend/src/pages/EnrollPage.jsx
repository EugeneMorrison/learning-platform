import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import api from '../api';

// /enroll/:courseId/ — target of "Начать бесплатно" on the public course page.
// Not logged in → register (with ?next= back here). Logged in → POST /api/enrollments/
// (idempotent), then into the course. Server errors (403/404) are shown as is.
function EnrollPage() {
    const { courseId } = useParams();
    const navigate = useNavigate();
    const [error, setError] = useState(null); // { message, courseSlug }
    const started = useRef(false);

    useEffect(() => {
        // StrictMode runs effects twice in dev; the endpoint is idempotent, but one call is enough.
        if (started.current) return;
        started.current = true;

        const here = `/enroll/${courseId}/`;
        const toRegister = () =>
            navigate(`/register/?next=${encodeURIComponent(here)}`, { replace: true });

        if (!localStorage.getItem('access_token')) {
            toRegister();
            return;
        }

        api.post('/enrollments/', { course: courseId })
            .then(() => navigate(`/courses/${courseId}/`, { replace: true }))
            .catch(err => {
                // 401 here means the session expired and the refresh failed (api.js cleared it).
                if (err.response?.status === 401) {
                    toRegister();
                    return;
                }
                setError({
                    message: err.response?.data?.detail
                        || 'Не удалось записаться на курс. Попробуйте позже.',
                    courseSlug: err.response?.data?.course_slug || null,
                });
            });
    }, [courseId, navigate]);

    if (!error) {
        return <p style={{ maxWidth: '400px', margin: '100px auto' }}>Записываем на курс…</p>;
    }

    return (
        <div style={{ maxWidth: '400px', margin: '100px auto', padding: '20px' }}>
            <h2>Не получилось записаться</h2>
            <p style={{ color: 'red' }}>{error.message}</p>
            <p>
                {/* Public course pages are Django-rendered, so a plain link (full page load). */}
                {error.courseSlug
                    ? <a href={`/course/${error.courseSlug}/`}>← Вернуться к курсу</a>
                    : <a href="/#catalog">← Все курсы</a>}
            </p>
            <p>
                <Link to="/dashboard/">Мой кабинет</Link>
            </p>
        </div>
    );
}

export default EnrollPage;
