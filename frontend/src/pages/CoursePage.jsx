import { useState, useEffect, useRef } from 'react';
import { Link, useParams, useNavigate, useSearchParams } from 'react-router-dom';
import api from '../api';
import ChatPanel from '../components/ChatPanel';
import CourseCoverEditor from '../components/CourseCoverEditor';
import EditableTitle from '../components/EditableTitle';
import StudentChat from '../components/StudentChat';
import { MAX_MESSAGE_LENGTH, mergeMessages, messageLength, useChatSocket } from '../lib/chatSocket';
import { COURSE_LEVELS, NO_LEVEL_LABEL } from '../lib/courseLevels';
import { badgeText, useActiveChat, useNotifications } from '../lib/notifications';
import '../components/Notifications.css';
import './CoursePage.css';

function CoursePage() {
    const { courseId } = useParams();
    const navigate = useNavigate();

    const [course, setCourse] = useState(null);
    const [lessons, setLessons] = useState([]);
    const [enrollments, setEnrollments] = useState([]);
    // A student enrolled in this course (not the owner): the floating chat with the author.
    const [isEnrolled, setIsEnrolled] = useState(false);
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [selectedStudent, setSelectedStudent] = useState(null);
    const [sendingMessage, setSendingMessage] = useState(false);
    const [historyError, setHistoryError] = useState(false);
    const [sendError, setSendError] = useState('');
    // The student whose chat is open, for async results (state would be stale
    // inside them): a response for anyone else is dropped.
    const selectedStudentIdRef = useRef(null);
    const chatButtonRefs = useRef({});

    // Lesson form state
    const [showLessonForm, setShowLessonForm] = useState(false);
    const [newLessonTitle, setNewLessonTitle] = useState('');
    const [creatingLesson, setCreatingLesson] = useState(false);

    // Lesson ↑ / ↓: one move at a time (a double click must not move twice).
    const [movingLesson, setMovingLesson] = useState(false);
    const [moveStatus, setMoveStatus] = useState(''); // for screen readers
    const movingRef = useRef(false);
    const moveButtonRefs = useRef({});

    // Level select: saved on change. Only the latest change's answer counts
    // (no disabling while saving: that would drop keyboard focus).
    const [levelStatus, setLevelStatus] = useState(''); // '' | 'saving' | 'saved' | 'error'
    const levelRequestRef = useRef(0);

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

                // Only the course's own author manages its students.
                if (courseRes.data.author === userRes.data.id) {
                    const enrollmentsRes = await api.get(`/courses/${courseId}/enrollments/`);
                    setEnrollments(enrollmentsRes.data);
                } else {
                    const mine = await api.get('/enrollments/');
                    setIsEnrolled(mine.data.some(e => String(e.course) === String(courseId)));
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

    // Move a lesson one place up (dir -1) or down (+1). The server renumbers
    // the course in one transaction and returns the list in the new order;
    // the "Урок N" labels follow the list position.
    async function handleMoveLesson(index, dir) {
        if (movingRef.current) return;
        const lesson = lessons[index];
        movingRef.current = true;
        setMovingLesson(true);
        setMoveStatus('');
        try {
            const res = await api.post(`/lessons/${lesson.id}/reorder/`, { new_order: index + 1 + dir });
            setLessons(res.data);
            const position = res.data.findIndex(l => l.id === lesson.id) + 1;
            setMoveStatus(`Урок «${lesson.title}» теперь ${position}-й.`);
            // Keep keyboard focus on the moved lesson's arrow (or the other
            // one once it reaches the top / bottom).
            requestAnimationFrame(() => {
                const same = moveButtonRefs.current[`${lesson.id}:${dir}`];
                const other = moveButtonRefs.current[`${lesson.id}:${-dir}`];
                (same && !same.disabled ? same : other)?.focus();
            });
        } catch (err) {
            console.error('Failed to move lesson:', err);
            alert('Не удалось переместить урок.');
        } finally {
            movingRef.current = false;
            setMovingLesson(false);
        }
    }

    // Rename: the server's answer is the source of truth for the new title.
    async function handleRenameCourse(title) {
        const res = await api.patch(`/courses/${courseId}/`, { title });
        setCourse(prev => ({ ...prev, title: res.data.title }));
    }

    // Level: shown at once, saved by PATCH; a failed save puts the server's
    // value back (refetched, since earlier changes may have been saved).
    async function handleLevelChange(e) {
        const level = e.target.value || null;
        const request = ++levelRequestRef.current;
        setCourse(prev => ({ ...prev, level }));
        setLevelStatus('saving');
        try {
            const res = await api.patch(`/courses/${courseId}/`, { level });
            if (request !== levelRequestRef.current) return;
            setCourse(prev => ({ ...prev, level: res.data.level }));
            setLevelStatus('saved');
        } catch (err) {
            if (request !== levelRequestRef.current) return;
            console.error('Failed to save course level:', err);
            setLevelStatus('error');
            try {
                const res = await api.get(`/courses/${courseId}/`);
                if (request === levelRequestRef.current) {
                    setCourse(prev => ({ ...prev, level: res.data.level }));
                }
            } catch {
                // Offline: the select keeps the unsaved value, the error says so.
            }
        }
    }

    async function handleRenameLesson(lessonId, title) {
        const res = await api.patch(`/lessons/${lessonId}/`, { title });
        setLessons(prev => prev.map(l => (l.id === lessonId ? { ...l, title: res.data.title } : l)));
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
            if (selectedStudentIdRef.current !== studentId) return; // switched or closed meanwhile
            const history = res.data.filter(m => m.sender === studentId || m.receiver === studentId);
            // Merge: messages that arrived live while this loaded stay.
            setMessages(prev => mergeMessages(prev, history));
            setHistoryError(false);
        } catch (err) {
            console.error('Failed to load messages:', err);
            if (selectedStudentIdRef.current === studentId) setHistoryError(true);
        }
    }

    // Socket while a student's chat is open; a new one per student (the old one
    // closes on switch, close, or leaving the page). Reconnects after a drop.
    const { status: chatStatus, send: sendChat, pending: chatPending } = useChatSocket({
        courseId,
        otherUserId: selectedStudent?.id,
        isOwn: msg => msg.sender !== selectedStudentIdRef.current,
        enabled: Boolean(selectedStudent),
        onMessage: msg => {
            const id = selectedStudentIdRef.current;
            if (msg.sender !== id && msg.receiver !== id) return;
            setMessages(prev => mergeMessages(prev, [msg]));
        },
        onRejected: frame => setSendError(frame.error === 'too_long'
            ? `Сообщение не отправлено: не больше ${frame.max_length} символов.`
            : 'Сообщение не отправлено.'),
        // Server saved it: clear the input, unless the user has typed on since.
        onConfirmed: text => setNewMessage(current => (current.trim() === text ? '' : current)),
        onReconnected: () => fetchMessages(selectedStudentIdRef.current),
    });

    async function handleSendMessage(e) {
        e.preventDefault();
        const text = newMessage.trim();
        if (!text || chatStatus !== 'open' || messageLength(text) > MAX_MESSAGE_LENGTH) return;
        setSendingMessage(true);
        try {
            // The input keeps the text until the server confirms it (onConfirmed).
            if (sendChat(text)) setSendError('');
        } catch (err) {
            console.error('Failed to send message:', err);
        } finally {
            setSendingMessage(false);
        }
    }

    function openChat(student) {
        selectedStudentIdRef.current = student.id;
        setMessages([]); // never show the previous student's conversation
        setHistoryError(false);
        setSendError('');
        setSelectedStudent(student);
        fetchMessages(student.id);
    }

    // Close button, Esc, or the student's "Чат" button again. Closing the
    // window closes the socket (effect cleanup), as leaving the page did.
    function closeChat() {
        const id = selectedStudent?.id;
        selectedStudentIdRef.current = null;
        setSelectedStudent(null);
        chatButtonRefs.current[id]?.focus();
    }


    // Unread counts per student; the open student chat counts as read.
    const notifications = useNotifications();
    useActiveChat(courseId, selectedStudent?.id, Boolean(selectedStudent));

    // Deep link from the bell / the dashboard: ?chat=<student id> opens that
    // student's chat (owner; ignored for a student not enrolled here), ?chat=1
    // the student's own chat with the author. The parameter goes once used.
    const [searchParams, setSearchParams] = useSearchParams();
    const studentChatRef = useRef(null);
    const chatParam = searchParams.get('chat');
    useEffect(() => {
        if (loading || !course || chatParam === null) return;
        if (user && course.author === user.id) {
            const enrollment = enrollments.find(e => String(e.student) === chatParam);
            if (enrollment) openChat({ id: enrollment.student, name: enrollment.student_name });
        } else if (chatParam === '1') {
            studentChatRef.current?.open();
        }
        setSearchParams(params => {
            params.delete('chat');
            return params;
        }, { replace: true });
        // openChat only sets state; it changes every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [loading, course, user, enrollments, chatParam, setSearchParams]);

    if (loading) return <div className="page"><p className="page-status">Загрузка...</p></div>;
    if (!course) return <div className="page"><p className="page-status">Курс не найден.</p></div>;

    // All author controls (add / edit / delete / move lessons, students,
    // enrolment) are for the author who owns this course. Any other user,
    // another author included, sees the course like a reader.
    const isOwner = Boolean(user && course.author === user.id);

    return (
        <div className="page">

            {/* Header */}
            <button className="btn btn-ghost btn-sm page__back" onClick={() => navigate('/dashboard/')}>
                ← Назад
            </button>
            <div className="page__header">
                <div>
                    <EditableTitle
                        as="h1"
                        className="page__title"
                        value={course.title}
                        canEdit={isOwner}
                        onSave={handleRenameCourse}
                    />
                    {isOwner && (
                        <div className="course-level">
                            <label className="course-level__label" htmlFor="course-level">Уровень</label>
                            <select
                                id="course-level"
                                className="input course-level__select"
                                value={course.level || ''}
                                onChange={handleLevelChange}
                                aria-describedby="course-level-status"
                            >
                                <option value="">{NO_LEVEL_LABEL}</option>
                                {COURSE_LEVELS.map(level => (
                                    <option key={level.value} value={level.value}>{level.label}</option>
                                ))}
                            </select>
                            <span
                                id="course-level-status"
                                className={levelStatus === 'error' ? 'course-level__status course-level__status--error' : 'course-level__status'}
                                role="status"
                            >
                                {levelStatus === 'saving' && 'Сохранение…'}
                                {levelStatus === 'saved' && 'Сохранено'}
                                {levelStatus === 'error' && 'Не удалось сохранить уровень. Попробуйте ещё раз.'}
                            </span>
                        </div>
                    )}
                    {isOwner && (
                        <CourseCoverEditor
                            courseId={courseId}
                            cover={course.cover}
                            onSaved={cover => setCourse(prev => ({ ...prev, cover }))}
                        />
                    )}
                    {course.description && <p className="page__lead">{course.description}</p>}
                </div>
            </div>

            <div className={isOwner ? 'course-layout course-layout--with-aside' : 'course-layout'}>

            {/* Lessons section */}
            <section className="section">
                <div className="section__header">
                    <h2 className="section__title">Уроки</h2>
                    {isOwner && (
                        <button className="btn btn-secondary btn-sm" onClick={() => setShowLessonForm(!showLessonForm)}>
                            {showLessonForm ? 'Отмена' : '+ Добавить урок'}
                        </button>
                    )}
                </div>

                {isOwner && showLessonForm && (
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

                <p className="visually-hidden" role="status">{moveStatus}</p>

                {lessons.length === 0 ? (
                    <p className="muted">Уроков пока нет.</p>
                ) : (
                    <div className="lesson-list">
                    {lessons.map((lesson, index) => (
                        <div key={lesson.id} className="card card-link lesson-row">
                            <div className="lesson-row__text">
                                <EditableTitle
                                    as="strong"
                                    className="lesson-row__title"
                                    value={lesson.title}
                                    canEdit={isOwner}
                                    onSave={title => handleRenameLesson(lesson.id, title)}
                                    display={
                                        <Link className="card-link__target" to={`/lesson/${lesson.id}/`}>
                                            Урок {index + 1}: {lesson.title}
                                        </Link>
                                    }
                                />
                                <p className="lesson-row__hint">→ Открыть урок</p>
                            </div>
                            {isOwner && (
                                <div className="lesson-row__actions">
                                    <button
                                        ref={el => { moveButtonRefs.current[`${lesson.id}:-1`] = el; }}
                                        className="btn btn-secondary btn-sm lesson-row__move"
                                        onClick={() => handleMoveLesson(index, -1)}
                                        disabled={movingLesson || index === 0}
                                        aria-label="Переместить выше"
                                        title="Переместить выше"
                                    >
                                        <span aria-hidden="true">↑</span>
                                    </button>
                                    <button
                                        ref={el => { moveButtonRefs.current[`${lesson.id}:1`] = el; }}
                                        className="btn btn-secondary btn-sm lesson-row__move"
                                        onClick={() => handleMoveLesson(index, 1)}
                                        disabled={movingLesson || index === lessons.length - 1}
                                        aria-label="Переместить ниже"
                                        title="Переместить ниже"
                                    >
                                        <span aria-hidden="true">↓</span>
                                    </button>
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

            {/* Students section: only for the course's own author */}
            {isOwner && (
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
                                            {(() => {
                                                const unread = notifications?.unreadFor(courseId, enrollment.student) || 0;
                                                return unread > 0 && selectedStudent?.id !== enrollment.student && (
                                                    <span className="unread-badge" aria-label={`непрочитанных: ${unread}`}>
                                                        {badgeText(unread)}
                                                    </span>
                                                );
                                            })()}
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
                                        sendError={sendError}
                                        value={newMessage}
                                        onChange={e => { setNewMessage(e.target.value); setSendError(''); }}
                                        onSubmit={handleSendMessage}
                                        sending={sendingMessage || chatPending}
                                        onClose={closeChat}
                                    />
                                )}
                            </div>
                        ))
                    )}
                </section>
            )}
            </div>

            {/* An enrolled student: the chat with the author (as on the lesson page). */}
            {!isOwner && isEnrolled && (
                <StudentChat
                    ref={studentChatRef}
                    course={course}
                    id="course-chat"
                    emptyHint="Задайте вопрос по курсу — учитель ответит здесь."
                />
            )}
        </div>
    );
}

export default CoursePage;