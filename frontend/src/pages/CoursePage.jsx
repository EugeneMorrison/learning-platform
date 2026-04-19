import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api';

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
        fetchAll();
    }, [courseId]);

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

    async function handleAddLesson(e) {
        e.preventDefault();
        if (!newLessonTitle.trim()) return;
        setCreatingLesson(true);
        try {
            await api.post('/lessons/', {
                course: courseId,
                title: newLessonTitle,
                order_index: lessons.length + 1,
            });
            setNewLessonTitle('');
            setShowLessonForm(false);
            const res = await api.get(`/lessons/?course=${courseId}`);
            setLessons(res.data);
        } catch (err) {
            console.error('Failed to create lesson:', err);
        } finally {
            setCreatingLesson(false);
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
        } catch (err) {
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
        if (!newMessage.trim() || !selectedStudent) return;
        setSendingMessage(true);
        try {
            await api.post('/messages/', {
                course: courseId,
                receiver: selectedStudent.id,
                text: newMessage,
            });
            setNewMessage('');
            await fetchMessages(selectedStudent.id);
        } catch (err) {
            console.error('Failed to send message:', err);
        } finally {
            setSendingMessage(false);
        }
    }


    if (loading) return <p>Загрузка...</p>;
    if (!course) return <p>Курс не найден.</p>;

    return (
        <div style={{ maxWidth: '800px', margin: '40px auto', padding: '20px' }}>

            {/* Header */}
            <button onClick={() => navigate('/dashboard/')} style={{ marginBottom: '20px' }}>
                ← Назад
            </button>
            <h2>{course.title}</h2>
            <p style={{ color: '#64748b' }}>{course.description}</p>
            <hr />

            {/* Lessons section */}
            <div style={{ marginTop: '24px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3>Уроки</h3>
                    {user?.role === 'AUTHOR' && (
                        <button onClick={() => setShowLessonForm(!showLessonForm)}>
                            {showLessonForm ? 'Отмена' : '+ Добавить урок'}
                        </button>
                    )}
                </div>

                {user?.role === 'AUTHOR' && showLessonForm && (
                    <form onSubmit={handleAddLesson} style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        padding: '16px',
                        marginTop: '12px',
                        background: '#f8fafc',
                    }}>
                        <input
                            type="text"
                            placeholder="Название урока"
                            value={newLessonTitle}
                            onChange={e => setNewLessonTitle(e.target.value)}
                            style={{ width: '100%', padding: '8px', marginBottom: '8px' }}
                            required
                        />
                        <button type="submit" disabled={creatingLesson}>
                            {creatingLesson ? 'Создание...' : 'Создать урок'}
                        </button>
                    </form>
                )}

                {lessons.length === 0 ? (
                    <p style={{ color: '#64748b' }}>Уроков пока нет.</p>
                ) : (
                    lessons.map((lesson, index) => (
                        <div key={lesson.id} style={{
                            border: '1px solid #e2e8f0',
                            borderRadius: '8px',
                            padding: '16px',
                            marginTop: '12px',
                            cursor: 'pointer',
                        }} onClick={() => navigate(`/lesson/${lesson.id}/`)}>
                            <strong>Урок {index + 1}: {lesson.title}</strong>
                            <p style={{ margin: '4px 0 0 0', color: '#64748b', fontSize: '14px' }}>
                                → Открыть урок
                            </p>
                        </div>
                    ))
                )}
            </div>

            {/* Students section — only for authors */}
            {user?.role === 'AUTHOR' && (
                <div style={{ marginTop: '32px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3>Студенты</h3>
                        <button onClick={() => setShowStudentForm(!showStudentForm)}>
                            {showStudentForm ? 'Отмена' : '+ Добавить студента'}
                        </button>
                    </div>

                    {showStudentForm && (
                        <form onSubmit={handleAddStudent} style={{
                            border: '1px solid #e2e8f0',
                            borderRadius: '8px',
                            padding: '16px',
                            marginTop: '12px',
                            background: '#f8fafc',
                        }}>
                            {studentError && <p style={{ color: 'red' }}>{studentError}</p>}
                            <input
                                type="text"
                                placeholder="Имя пользователя студента"
                                value={studentUsername}
                                onChange={e => setStudentUsername(e.target.value)}
                                style={{ width: '100%', padding: '8px', marginBottom: '8px' }}
                                required
                            />
                            <button type="submit" disabled={addingStudent}>
                                {addingStudent ? 'Добавление...' : 'Добавить'}
                            </button>
                        </form>
                    )}

                    {enrollments.length === 0 ? (
                        <p style={{ color: '#64748b' }}>Студентов пока нет.</p>
                    ) : (
                        enrollments.map(enrollment => (
                            <div key={enrollment.id} style={{
                                border: '1px solid #e2e8f0',
                                borderRadius: '8px',
                                padding: '16px',
                                marginTop: '12px',
                            }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <strong>{enrollment.student_name}</strong>
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <button onClick={() => navigate(`/courses/${courseId}/students/${enrollment.student}/`)}>
                                            Прогресс
                                        </button>
                                        <button onClick={() => {
                                            setSelectedStudent({ id: enrollment.student, name: enrollment.student_name });
                                            fetchMessages(enrollment.student);
                                        }}>
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
                </div>
            )}
        </div>
    );
}

export default CoursePage;