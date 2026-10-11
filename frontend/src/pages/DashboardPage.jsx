import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { logout } from '../api';
import './DashboardPage.css';

function DashboardPage() {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    useEffect(() => {
        async function fetchUser() {
            try {
                const response = await api.get('/auth/me/');
                setUser(response.data);
            } catch {
                navigate('/login/');
            } finally {
                setLoading(false);
            }
        }
        fetchUser();
        // navigate is stable while this page is mounted (it only changes with the
        // location, and the only navigation here unmounts the page), so no refetch loop.
    }, [navigate]);

    function handleLogout() {
        logout();
        navigate('/login/');
    }

    if (loading) return <div className="page"><p className="page-status">Загрузка...</p></div>;

    return (
        <div className="page">
            <div className="page__header">
                <div>
                    <h1 className="page__title">Добро пожаловать, {user.username}!</h1>
                    <p className="page__lead">Роль: {user.role === 'AUTHOR' ? 'Автор' : 'Студент'}</p>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={handleLogout}>Выйти</button>
            </div>
            {user.role === 'AUTHOR' ? <AuthorDashboard /> : <StudentDashboard user={user} />}
        </div>
    );
}

function StudentDashboard({ user }) {
    const [enrollments, setEnrollments] = useState([]);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    useEffect(() => {
        async function fetchEnrollments() {
            try {
                const response = await api.get('/enrollments/');
                setEnrollments(response.data);
            } catch (err) {
                console.error('Failed to load enrollments:', err);
            } finally {
                setLoading(false);
            }
        }
        fetchEnrollments();
    }, []);

    if (loading) return <p className="page-status">Загрузка курсов...</p>;

    return (
        <section className="section">
            <div className="section__header">
                <h2 className="section__title">Мои курсы</h2>
            </div>
            {enrollments.length === 0 ? (
                <p className="muted">Вы пока не записаны ни на один курс.</p>
            ) : (
                <div className="card-grid">
                    {enrollments.map(enrollment => (
                        <div
                            key={enrollment.id}
                            className="card card-link dash-card"
                            onClick={() => navigate(`/courses/${enrollment.course}/`)}
                        >
                            <h3 className="dash-card__title">{enrollment.course_title}</h3>
                            <p className="dash-card__meta">
                                Записан: {new Date(enrollment.enrolled_at).toLocaleDateString('ru-RU')}
                            </p>
                            <div className="dash-card__actions">
                                <button
                                    className="btn btn-secondary btn-sm"
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        navigate(`/courses/${enrollment.course}/students/${user.id}/`);
                                    }}
                                >
                                    Прогресс
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}

function AuthorDashboard() {
    const navigate = useNavigate();
    const [courses, setCourses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [newTitle, setNewTitle] = useState('');
    const [newDescription, setNewDescription] = useState('');
    const [creating, setCreating] = useState(false);

    useEffect(() => {
        fetchCourses();
    }, []);

    async function fetchCourses() {
        try {
            const response = await api.get('/courses/my_courses/');
            setCourses(response.data);
        } catch (err) {
            console.error('Failed to load courses:', err);
        } finally {
            setLoading(false);
        }
    }

    async function handleCreateCourse(e) {
        e.preventDefault();
        if (!newTitle.trim()) return;
        setCreating(true);
        try {
            await api.post('/courses/', {
                title: newTitle,
                description: newDescription,
            });
            setNewTitle('');
            setNewDescription('');
            setShowForm(false);
            await fetchCourses();
        } catch (err) {
            console.error('Failed to create course:', err);
        } finally {
            setCreating(false);
        }
    }

    if (loading) return <p className="page-status">Загрузка курсов...</p>;

    return (
        <section className="section">
            <div className="section__header">
                <h2 className="section__title">Мои курсы</h2>
                <button className="btn btn-secondary btn-sm" onClick={() => setShowForm(!showForm)}>
                    {showForm ? 'Отмена' : '+ Создать курс'}
                </button>
            </div>

            {showForm && (
                <form onSubmit={handleCreateCourse} className="inline-form dash-form">
                    <input
                        className="input"
                        type="text"
                        placeholder="Название курса"
                        aria-label="Название курса"
                        value={newTitle}
                        onChange={e => setNewTitle(e.target.value)}
                        required
                    />
                    <textarea
                        className="input"
                        placeholder="Описание курса"
                        aria-label="Описание курса"
                        value={newDescription}
                        onChange={e => setNewDescription(e.target.value)}
                    />
                    <button type="submit" className="btn btn-primary" disabled={creating}>
                        {creating ? 'Создание...' : 'Создать'}
                    </button>
                </form>
            )}

            {courses.length === 0 ? (
                <p className="muted">У вас пока нет курсов.</p>
            ) : (
                <div className="card-grid">
                    {courses.map(course => (
                        <div
                            key={course.id}
                            className="card card-link dash-card"
                            onClick={() => navigate(`/courses/${course.id}/`)}
                        >
                            <h3 className="dash-card__title">{course.title}</h3>
                            <p className="dash-card__desc">{course.description}</p>
                            <div className="dash-card__actions">
                                <span className="pill">Уроков: {course.lesson_count}</span>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}

export default DashboardPage;