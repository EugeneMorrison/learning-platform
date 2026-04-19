import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { logout } from '../api';

function DashboardPage() {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    useEffect(() => {
        async function fetchUser() {
            try {
                const response = await api.get('/auth/me/');
                setUser(response.data);
            } catch (err) {
                navigate('/login/');
            } finally {
                setLoading(false);
            }
        }
        fetchUser();
    }, []);

    function handleLogout() {
        logout();
        navigate('/login/');
    }

    if (loading) return <p>Загрузка...</p>;

    return (
        <div style={{ maxWidth: '800px', margin: '40px auto', padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2>Добро пожаловать, {user.username}!</h2>
                <button onClick={handleLogout}>Выйти</button>
            </div>
            <p>Роль: {user.role === 'AUTHOR' ? 'Автор' : 'Студент'}</p>
            <hr />
            {user.role === 'AUTHOR' ? <AuthorDashboard /> : <StudentDashboard />}
        </div>
    );
}

function StudentDashboard() {
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

    if (loading) return <p>Загрузка курсов...</p>;

    return (
        <div>
            <h3>Мои курсы</h3>
            {enrollments.length === 0 ? (
                <p style={{ color: '#64748b' }}>Вы пока не записаны ни на один курс.</p>
            ) : (
                enrollments.map(enrollment => (
                    <div key={enrollment.id} style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        padding: '16px',
                        marginTop: '12px',
                        cursor: 'pointer',
                    }} onClick={() => navigate(`/courses/${enrollment.course}/`)}>
                        <h4 style={{ margin: '0 0 8px 0' }}>{enrollment.course_title}</h4>
                        <p style={{ margin: '0', color: '#64748b', fontSize: '14px' }}>
                            Записан: {new Date(enrollment.enrolled_at).toLocaleDateString('ru-RU')}
                        </p>
                    </div>
                ))
            )}
        </div>
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

    if (loading) return <p>Загрузка курсов...</p>;

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3>Мои курсы</h3>
                <button onClick={() => setShowForm(!showForm)}>
                    {showForm ? 'Отмена' : '+ Создать курс'}
                </button>
            </div>

            {showForm && (
                <form onSubmit={handleCreateCourse} style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: '8px',
                    padding: '16px',
                    marginTop: '12px',
                    background: '#f8fafc',
                }}>
                    <div style={{ marginBottom: '12px' }}>
                        <input
                            type="text"
                            placeholder="Название курса"
                            value={newTitle}
                            onChange={e => setNewTitle(e.target.value)}
                            style={{ width: '100%', padding: '8px' }}
                            required
                        />
                    </div>
                    <div style={{ marginBottom: '12px' }}>
                        <textarea
                            placeholder="Описание курса"
                            value={newDescription}
                            onChange={e => setNewDescription(e.target.value)}
                            style={{ width: '100%', padding: '8px', minHeight: '80px' }}
                        />
                    </div>
                    <button type="submit" disabled={creating}>
                        {creating ? 'Создание...' : 'Создать'}
                    </button>
                </form>
            )}

            {courses.length === 0 ? (
                <p>У вас пока нет курсов.</p>
            ) : (
                courses.map(course => (
                    <div key={course.id} style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        padding: '16px',
                        marginTop: '12px',
                        cursor: 'pointer',
                    }} onClick={() => navigate(`/courses/${course.id}/`)}>

                        <h4 style={{ margin: '0 0 8px 0' }}>{course.title}</h4>
                        <p style={{ margin: '0', color: '#64748b', fontSize: '14px' }}>
                            {course.description}
                        </p>
                        <p style={{ margin: '8px 0 0 0', fontSize: '14px' }}>
                            Уроков: {course.lesson_count}
                        </p>
                    </div>
                ))
            )}
        </div>
    );
}

export default DashboardPage;