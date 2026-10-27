import { useState, useEffect } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import api from '../api';
import { COURSE_LEVELS, NO_LEVEL_LABEL } from '../lib/courseLevels';
import { plural } from '../lib/plural';
import { badgeText, conversationLink, formatMessageTime, useNotifications } from '../lib/notifications';
import CourseCover from '../components/CourseCover';
import DiscussionReports from '../components/DiscussionReports';
import { TaskProgress } from '../components/LessonProgress';
import '../components/Notifications.css';
import './DashboardPage.css';

function DashboardPage() {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();
    const location = useLocation();
    // Set by RegisterPage after a successful sign-up; shown once.
    const [justRegistered] = useState(() => Boolean(location.state?.justRegistered));

    // Clear that state from the history entry so a refresh (or Back to this
    // entry) doesn't show the notice again. Same pathname, so navigate stays
    // stable and the user isn't fetched twice.
    useEffect(() => {
        if (location.state?.justRegistered) {
            navigate(location.pathname, { replace: true, state: null });
        }
    }, [location, navigate]);

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
        // pathname; the one same-path replace above keeps it), so no refetch loop.
    }, [navigate]);

    if (loading) return <div className="page"><p className="page-status">Загрузка...</p></div>;

    return (
        <div className="page">
            {justRegistered && (
                <p className="notice notice-success dash-notice" role="status">Вы успешно зарегистрированы</p>
            )}
            <div className="page__header">
                <div>
                    <h1 className="page__title">Добро пожаловать, {withBreakHints(user.username)}!</h1>
                    <p className="page__lead">Роль: {user.role === 'AUTHOR' ? 'Автор' : 'Студент'}</p>
                </div>
            </div>
            {user.role === 'AUTHOR' && <StudentQuestions />}
            {user.role === 'AUTHOR' && <DiscussionReports />}
            {user.role === 'AUTHOR' ? <AuthorDashboard /> : <StudentDashboard user={user} />}
        </div>
    );
}

// Long usernames ("regtest_mv5nszqd_phone"): offer line breaks after _ . - @
// so a narrow screen wraps between parts instead of mid-word.
function withBreakHints(name) {
    return name.split(/(?<=[_.\-@])/).flatMap((part, i) => (i ? [<wbr key={i} />, part] : [part]));
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
                        <div key={enrollment.id} className="card card-link dash-card">
                            <div className="dash-card__cover">
                                <CourseCover title={enrollment.course_title} cover={enrollment.course_cover} />
                            </div>
                            <h3 className="dash-card__title">
                                <Link className="card-link__target" to={`/courses/${enrollment.course}/`}>
                                    {enrollment.course_title}
                                </Link>
                            </h3>
                            <p className="dash-card__meta">
                                Записан: {new Date(enrollment.enrolled_at).toLocaleDateString('ru-RU')}
                            </p>
                            {/* Course progress, as on the course page; nothing for a course without tasks. */}
                            {enrollment.task_count > 0 && (
                                <div className="dash-card__progress">
                                    <TaskProgress
                                        solved={enrollment.solved_count}
                                        total={enrollment.task_count}
                                        completeText="✓ Курс пройден"
                                    />
                                </div>
                            )}
                            <div className="dash-card__actions">
                                <button
                                    className="btn btn-secondary btn-sm"
                                    onClick={() => navigate(`/courses/${enrollment.course}/students/${user.id}/`)}
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

// «Вопросы студентов»: conversations where students wrote to me (the author)
// and I haven't read it yet. Unread questions («Задать вопрос») first, then
// plain messages; newest first within each. Live (lib/notifications.js).
function StudentQuestions() {
    const notifications = useNotifications();
    const conversations = (notifications?.conversations || [])
        .filter(c => !c.other_is_author)
        .sort((a, b) => (Number(b.has_question) - Number(a.has_question))
            || String(b.last_message.created_at).localeCompare(String(a.last_message.created_at))
            || b.last_message.id - a.last_message.id);

    return (
        <section className="section">
            <div className="section__header">
                <h2 className="section__title">Вопросы студентов</h2>
            </div>
            {conversations.length === 0 ? (
                <p className="muted">Новых сообщений от студентов нет.</p>
            ) : (
                <ul className="inbox-list">
                    {conversations.map(c => (
                        <li key={`${c.course_id}:${c.other_user_id}`}>
                            <Link className="inbox-item" to={conversationLink(c)}>
                                <span className="inbox-item__main">
                                    <span className="inbox-item__who">{c.other_user_name} · {c.course_title}</span>
                                    <span className="inbox-item__preview">
                                        {c.has_question && <span className="question-chip">Вопрос</span>}
                                        {c.last_message.preview}
                                    </span>
                                    <time className="inbox-item__time" dateTime={c.last_message.created_at}>
                                        {formatMessageTime(c.last_message.created_at)}
                                    </time>
                                </span>
                                <span className="unread-badge" aria-label={`непрочитанных: ${c.unread_count}`}>
                                    {badgeText(c.unread_count)}
                                </span>
                            </Link>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}

function AuthorDashboard() {
    const [courses, setCourses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [newTitle, setNewTitle] = useState('');
    const [newDescription, setNewDescription] = useState('');
    const [newLevel, setNewLevel] = useState(''); // '' = «Не указан» (null)
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
                level: newLevel || null,
            });
            setNewTitle('');
            setNewDescription('');
            setNewLevel('');
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
                    <label className="dash-form__level">
                        <span className="field__label">Уровень</span>
                        <select
                            className="input"
                            value={newLevel}
                            onChange={e => setNewLevel(e.target.value)}
                        >
                            <option value="">{NO_LEVEL_LABEL}</option>
                            {COURSE_LEVELS.map(level => (
                                <option key={level.value} value={level.value}>{level.label}</option>
                            ))}
                        </select>
                    </label>
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
                        <div key={course.id} className="card card-link dash-card">
                            <div className="dash-card__cover">
                                <CourseCover title={course.title} cover={course.cover} />
                            </div>
                            <h3 className="dash-card__title">
                                <Link className="card-link__target" to={`/courses/${course.id}/`}>
                                    {course.title}
                                </Link>
                            </h3>
                            <p className="dash-card__desc">{course.description}</p>
                            {/* Students' average, then the author's own solving; nothing without tasks. */}
                            {course.task_count > 0 && (
                                <div className="dash-card__progress">
                                    {course.student_count > 0 ? (
                                        <TaskProgress
                                            solved={course.students_solved}
                                            total={course.task_count * course.student_count}
                                            label={`${plural(course.student_count, 'студент', 'студента', 'студентов')} · в среднем`}
                                            ariaLabel="Студенты в среднем решили"
                                            completeText="✓ Все прошли курс"
                                        />
                                    ) : (
                                        <p className="dash-card__meta">Студентов пока нет</p>
                                    )}
                                    <p className="dash-card__meta dash-card__own">
                                        Вы решили {course.solved_count} из {course.task_count} задач
                                    </p>
                                </div>
                            )}
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