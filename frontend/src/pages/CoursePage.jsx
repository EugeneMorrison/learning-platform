import { useState, useEffect, useRef } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import api from '../api';
import ChatPanel from '../components/ChatPanel';
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
    // UI only: what the window shows about the socket and the history fetch.
    const [chatStatus, setChatStatus] = useState('connecting');
    const [historyError, setHistoryError] = useState(false);
    const chatSocketRef = useRef(null);
    const chatButtonRefs = useRef({});

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
        setHistoryError(true);
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

        // Status for the window only; a socket replaced by a newer one is ignored.
        socket.onopen = () => {
            if (chatSocketRef.current === socket) setChatStatus('open');
        };
        socket.onclose = () => {
            if (chatSocketRef.current === socket) setChatStatus('closed');
        };

        return () => {
            chatSocketRef.current = null;
            if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
                socket.close();
            }
        };
    }, [selectedStudent, courseId]);

    function openChat(student) {
        setChatStatus('connecting');
        setHistoryError(false);
        setSelectedStudent(student);
        fetchMessages(student.id);
    }

    // Close button, Esc, or the student's "Чат" button again. Closing the
    // window closes the socket (effect cleanup), as leaving the page did.
    function closeChat() {
        const id = selectedStudent?.id;
        setSelectedStudent(null);
        chatButtonRefs.current[id]?.focus();
    }


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
                                            ref={el => { chatButtonRefs.current[enrollment.student] = el; }}
                                            className="btn btn-secondary btn-sm"
                                            aria-expanded={selectedStudent?.id === enrollment.student}
                                            aria-controls={selectedStudent?.id === enrollment.student ? `student-chat-${enrollment.student}` : undefined}
                                            onClick={() => (selectedStudent?.id === enrollment.student
                                                ? closeChat()
                                                : openChat({ id: enrollment.student, name: enrollment.student_name }))}
                                        >
                                            Чат
                                        </button>
                                    </div>
                                </div>

                                {/* Chat window */}
                                {selectedStudent?.id === enrollment.student && (
                                    <ChatPanel
                                        id={`student-chat-${enrollment.student}`}
                                        variant="inline"
                                        headingLevel={3}
                                        title="Чат со студентом"
                                        subtitle={enrollment.student_name}
                                        messages={messages}
                                        isOwn={msg => msg.sender !== enrollment.student}
                                        emptyHint="Напишите студенту первым — ответ появится здесь."
                                        status={chatStatus}
                                        historyError={historyError}
                                        value={newMessage}
                                        onChange={e => setNewMessage(e.target.value)}
                                        onSubmit={handleSendMessage}
                                        sending={sendingMessage}
                                        onClose={closeChat}
                                    />
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