import { useState, useEffect, useRef } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import api from '../api';
import './CoursePage.css';

function CoursePage() {
    const { courseId } = useParams();
    const navigate = useNavigate();

    const [course, setCourse] = useState(null);
    const [lessons, setLessons] = useState([]);
    const [enrollments, setEnrollments] = useState([]);
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [selectedStudent, setSelectedStudent] = useState(null);
    const [sendingMessage, setSendingMessage] = useState(false);
    const chatSocketRef = useRef(null);

    // Lesson form state
    const [showLessonForm, setShowLessonForm] = useState(false);
    const [newLessonTitle, setNewLessonTitle] = useState('');
    const [creatingLesson, setCreatingLesson] = useState(false);

    // Student form state
    const [showStudentForm, setShowStudentForm] = useState(false);
    const [studentUsername, setStudentUsername] = useState('');
    const [addingStudent, setAddingStudent] = useState(false);
    const [studentError, setStudentError] = useState('');

    useEffect(() => {
        // Defined inside the effect so courseId is its only dependency
        // (a component-level function would change every render and refetch in a loop).
        async function fetchAll() {
            try {
                const userRes = await api.get('/auth/me/');
                setUser(userRes.data);

                const [courseRes, lessonsRes] = await Promise.all([
                    api.get(`/courses/${courseId}/`),
                    api.get(`/lessons/?course=${courseId}`),
                ]);
                setCourse(courseRes.data);
                setLessons(lessonsRes.data);

                // Only fetch enrollments for authors
                if (userRes.data.role === 'AUTHOR') {
                    const enrollmentsRes = await api.get(`/courses/${courseId}/enrollments/`);
                    setEnrollments(enrollmentsRes.data);
                }
            } catch (err) {
                console.error('Failed to load course:', err);
            } finally {
                setLoading(false);
            }
        }
        fetchAll();
    }, [courseId]);

    async function handleAddLesson(e) {
        e.preventDefault();
        if (!newLessonTitle.trim()) return;
        setCreatingLesson(true);
        try {
            // Use max(order_index)+1, not length+1: deleting a lesson leaves a
            // gap, so length+1 can collide with an existing order_index and the
            // serializer's unique-together check rejects the create.
            const nextOrder = lessons.length
                ? Math.max(...lessons.map(l => l.order_index)) + 1
                : 1;
            await api.post('/lessons/', {
                course: courseId,
                title: newLessonTitle,
                order_index: nextOrder,
            });
            setNewLessonTitle('');
            setShowLessonForm(false);
            const res = await api.get(`/lessons/?course=${courseId}`);
            setLessons(res.data);
        } catch (err) {
            console.error('Failed to create lesson:', err);
            alert('Не удалось создать урок. Попробуйте ещё раз.');
        } finally {
            setCreatingLesson(false);
        }
    }

    async function handleDeleteLesson(lessonId) {
        if (!window.confirm('Вы уверены, что хотите удалить урок?')) return;
        try {
            await api.delete(`/lessons/${lessonId}/`);
            setLessons(lessons.filter(l => l.id !== lessonId));
        } catch (err) {
            console.error('Failed to delete lesson:', err);
            alert('Не удалось удалить урок.');
        }
    }

    async function handleAddStudent(e) {
        e.preventDefault();
        setStudentError('');
        setAddingStudent(true);
        try {
            await api.post(`/courses/${courseId}/enroll_student/`, {
                username: studentUsername,
            });
            setStudentUsername('');
            setShowStudentForm(false);
            const res = await api.get(`/courses/${courseId}/enrollments/`);
            setEnrollments(res.data);
        } catch {
            setStudentError('Студент не найден или уже записан на курс.');
        } finally {
            setAddingStudent(false);
        }
    }

    async function fetchMessages(studentId) {
    try {
        const res = await api.get(`/messages/?course=${courseId}`);
        setMessages(res.data.filter(m =>
            m.sender === studentId || m.receiver === studentId
        ));
    } catch (err) {
        console.error('Failed to load messages:', err);
    }
}

    async function handleSendMessage(e) {
        e.preventDefault();
        const text = newMessage.trim();
        if (!text || !chatSocketRef.current || chatSocketRef.current.readyState !== WebSocket.OPEN) return;
        setSendingMessage(true);
        try {
            chatSocketRef.current.send(JSON.stringify({ text }));
            setNewMessage('');
        } catch (err) {
            console.error('Failed to send message:', err);
        } finally {
            setSendingMessage(false);
        }
    }

    // Open WebSocket while a student is selected for chat. Closes when the
    // teacher switches student or leaves the page.
    useEffect(() => {
        if (!selectedStudent) return;

        const token = localStorage.getItem('access_token');
        const wsBase = import.meta.env.DEV
            ? 'ws://127.0.0.1:8000'
            : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
        const url = `${wsBase}/ws/chat/${courseId}/${selectedStudent.id}/?token=${encodeURIComponent(token || '')}`;

        const socket = new WebSocket(url);
        chatSocketRef.current = socket;

        socket.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                setMessages((prev) => [...prev, msg]);
            } catch (err) {
                console.error('Bad chat message payload:', err);
            }
        };

        socket.onerror = (err) => {
            console.error('Chat socket error:', err);
        };

        return () => {
            chatSocketRef.current = null;
            if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
                socket.close();
            }
        };
    }, [selectedStudent, courseId]);


    if (loading) return <div className="page"><p className="page-status">Загрузка...</p></div>;
    if (!course) return <div className="page"><p className="page-status">Курс не найден.</p></div>;

    const isAuthor = user?.role === 'AUTHOR';

    return (
        <div className="page">

            {/* Header */}
            <button className="btn btn-ghost btn-sm page__back" onClick={() => navigate('/dashboard/')}>
                ← Назад
            </button>
            <div className="page__header">
                <div>
                    <h1 className="page__title">{course.title}</h1>
                    {course.description && <p className="page__lead">{course.description}</p>}
                </div>
            </div>

            <div className={isAuthor ? 'course-layout course-layout--with-aside' : 'course-layout'}>

            {/* Lessons section */}
            <section className="section">
                <div className="section__header">
                    <h2 className="section__title">Уроки</h2>
                    {isAuthor && (
                        <button className="btn btn-secondary btn-sm" onClick={() => setShowLessonForm(!showLessonForm)}>
                            {showLessonForm ? 'Отмена' : '+ Добавить урок'}
                        </button>
                    )}
                </div>

                {isAuthor && showLessonForm && (
                    <form onSubmit={handleAddLesson} className="inline-form">
                        <input
                            className="input"
                            type="text"
                            placeholder="Название урока"
                            aria-label="Название урока"
                            value={newLessonTitle}
                            onChange={e => setNewLessonTitle(e.target.value)}
                            required
                        />
                        <button type="submit" className="btn btn-primary" disabled={creatingLesson}>
                            {creatingLesson ? 'Создание...' : 'Создать урок'}
                        </button>
                    </form>
                )}

                {lessons.length === 0 ? (
                    <p className="muted">Уроков пока нет.</p>
                ) : (
                    <div className="lesson-list">
                    {lessons.map((lesson, index) => (
                        <div key={lesson.id} className="card card-link lesson-row">
                            <div className="lesson-row__text">
                                <strong className="lesson-row__title">
                                    <Link className="card-link__target" to={`/lesson/${lesson.id}/`}>
                                        Урок {index + 1}: {lesson.title}
                                    </Link>
                                </strong>
                                <p className="lesson-row__hint">→ Открыть урок</p>
                            </div>
                            {isAuthor && (
                                <div className="lesson-row__actions">
                                    <button
                                        className="btn btn-secondary btn-sm"
                                        onClick={() => navigate(`/lesson/${lesson.id}/edit/`)}
                                    >
                                        ✎ Редактировать
                                    </button>
                                    <button
                                        className="btn btn-danger btn-sm"
                                        onClick={() => handleDeleteLesson(lesson.id)}
                                    >
                                        Удалить урок
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                    </div>
                )}
            </section>

            {/* Students section — only for authors */}
            {isAuthor && (
                <section className="section course-students">
                    <div className="section__header">
                        <h2 className="section__title">Студенты</h2>
                        <button className="btn btn-secondary btn-sm" onClick={() => setShowStudentForm(!showStudentForm)}>
                            {showStudentForm ? 'Отмена' : '+ Добавить студента'}
                        </button>
                    </div>

                    {showStudentForm && (
                        <form onSubmit={handleAddStudent} className="inline-form">
                            {studentError && <p className="notice notice-danger" role="alert">{studentError}</p>}
                            <input
                                className="input"
                                type="text"
                                placeholder="Имя пользователя студента"
                                aria-label="Имя пользователя студента"
                                value={studentUsername}
                                onChange={e => setStudentUsername(e.target.value)}
                                required
                            />
                            <button type="submit" className="btn btn-primary" disabled={addingStudent}>
                                {addingStudent ? 'Добавление...' : 'Добавить'}
                            </button>
                        </form>
                    )}

                    {enrollments.length === 0 ? (
                        <p className="muted">Студентов пока нет.</p>
                    ) : (
                        enrollments.map(enrollment => (
                            <div key={enrollment.id} className="card student-row">
                                <div className="student-row__head">
                                    <strong className="student-row__name">{enrollment.student_name}</strong>
                                    <div className="student-row__actions">
                                        <button
                                            className="btn btn-secondary btn-sm"
                                            onClick={() => navigate(`/courses/${courseId}/students/${enrollment.student}/`)}
                                        >
                                            Прогресс
                                        </button>
                                        <button
                                            className="btn btn-secondary btn-sm"
                                            onClick={() => {
                                                setSelectedStudent({ id: enrollment.student, name: enrollment.student_name });
                                                fetchMessages(enrollment.student);
                                            }}
                                        >
                                            💬 Чат
                                        </button>
                                    </div>
                                </div>

                                {/* Chat window */}
                                {selectedStudent?.id === enrollment.student && (
                                    <div style={{ marginTop: '16px' }}>
                                        <div style={{
                                            border: '1px solid #e2e8f0',
                                            borderRadius: '8px',
                                            padding: '12px',
                                            minHeight: '150px',
                                            maxHeight: '300px',
                                            overflowY: 'auto',
                                            background: '#f8fafc',
                                            marginBottom: '8px',
                                        }}>
                                            {messages.length === 0 ? (
                                                <p style={{ color: '#94a3b8', textAlign: 'center' }}>
                                                    Сообщений пока нет
                                                </p>
                                            ) : (
                                                messages.map(msg => (
                                                    <div key={msg.id} style={{
                                                        marginBottom: '8px',
                                                        textAlign: msg.sender === enrollment.student ? 'left' : 'right',
                                                    }}>
                                                        <span style={{
                                                            display: 'inline-block',
                                                            background: msg.sender === enrollment.student ? 'white' : '#0C4B33',
                                                            color: msg.sender === enrollment.student ? '#333' : 'white',
                                                            padding: '8px 12px',
                                                            borderRadius: '8px',
                                                            fontSize: '14px',
                                                            maxWidth: '70%',
                                                        }}>
                                                            <strong>{msg.sender_username}:</strong> {msg.text}
                                                        </span>
                                                    </div>
                                                ))
                                            )}
                                        </div>
                                        <form onSubmit={handleSendMessage} style={{ display: 'flex', gap: '8px' }}>
                                            <input
                                                type="text"
                                                placeholder="Написать сообщение..."
                                                value={newMessage}
                                                onChange={e => setNewMessage(e.target.value)}
                                                style={{ flex: 1, padding: '8px' }}
                                            />
                                            <button type="submit" disabled={sendingMessage}>
                                                {sendingMessage ? '...' : 'Отправить'}
                                            </button>
                                        </form>
                                    </div>
                                )}
                            </div>
                        ))
                    )}
                </section>
            )}
            </div>
        </div>
    );
}

export default CoursePage;