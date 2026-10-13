import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getLesson, getBlocks } from '../api';
import api from '../api';
import TextBlock from '../components/TextBlock';
import QuizBlock from '../components/QuizBlock';
import CodeBlock from '../components/CodeBlock';
import FillBlock from '../components/FillBlock';
import ChatPanel, { ChatIcon, CloseIcon } from '../components/ChatPanel';
import { watchFigureOverflow } from '../lib/contentImages';
import { MAX_MESSAGE_LENGTH, mergeMessages, messageLength, useChatSocket } from '../lib/chatSocket';
import './LessonViewer.css';

// Block types that are solvable tasks (have a pass/fail, count toward progress).
const TASK_TYPES = new Set(['QUIZ', 'CODE', 'FILL']);

const DEV_LESSON_ID = '6f1c0c31-7be5-4434-ac25-c00f8031d15c';

function getLessonIdFromUrl() {
    const parts = window.location.pathname.split('/');
    const idx = parts.indexOf('lesson');
    if (idx !== -1 && parts[idx + 1]) return parts[idx + 1];
    return import.meta.env.DEV ? DEV_LESSON_ID : null;
}

function LessonViewer() {
    const navigate = useNavigate();
    const isInIframe = window.self !== window.top;

    const [lesson, setLesson] = useState(null);
    const [blocks, setBlocks] = useState([]);
    const [course, setCourse] = useState(null);
    const [user, setUser] = useState(null);
    const [progress, setProgress] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showChat, setShowChat] = useState(false);
    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [sendingMessage, setSendingMessage] = useState(false);
    const [historyError, setHistoryError] = useState(false);
    const [sendError, setSendError] = useState('');
    const chatButtonRef = useRef(null);

    const solvedBlockIds = new Set(
        progress.filter(p => p.is_correct === true).map(p => p.block)
    );
    const firstUnresolved = blocks.find(
        b => TASK_TYPES.has(b.type) && !solvedBlockIds.has(b.id)
    );

    function scrollToNextTask() {
        if (!firstUnresolved) return;
        const el = document.getElementById(`block-${firstUnresolved.id}`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    useEffect(() => {
        loadLesson();
    }, []);

    // Fade at the right edge of formula boxes that scroll sideways (phones).
    useEffect(() => {
        if (loading) return undefined;
        return watchFigureOverflow(document.querySelector('.lesson-page'));
    }, [loading, blocks]);

    async function loadLesson() {
        try {
            const lessonId = getLessonIdFromUrl();
            if (!lessonId) {
                setError({ message: 'Lesson ID not found in URL.' });
                setLoading(false);
                return;
            }
            const [lessonResponse, blocksResponse] = await Promise.all([
                getLesson(lessonId),
                getBlocks(lessonId),
            ]);
            setLesson(lessonResponse.data);
            setBlocks(blocksResponse.data);
            const courseResponse = await api.get(`/courses/${lessonResponse.data.course}/`);
            setCourse(courseResponse.data);
            try {
                const userResponse = await api.get('/auth/me/');
                setUser(userResponse.data);
            } catch {
                setUser(null);
            }
            try {
                const progressResponse = await api.get(`/progress/course/${lessonResponse.data.course}/`);
                setProgress(progressResponse.data);
            } catch {
                setProgress([]);
            }
        } catch (err) {
            const status = err.response?.status;
            if (status === 401 || status === 404) {
                // No access (anonymous, or not enrolled) — lessons open only after enrolment.
                // The API adds course_slug only when the lesson's course is published.
                const slug = err.response?.data?.course_slug;
                // Read the token now: api.js clears it if the session had expired.
                const loggedIn = Boolean(localStorage.getItem('access_token'));
                setError(slug ? {
                    message: loggedIn
                        ? 'Запишитесь на курс, чтобы открыть урок'
                        : 'Чтобы открыть урок, войдите и запишитесь на курс',
                    href: `/course/${slug}/`,
                    linkLabel: 'Перейти к курсу',
                } : {
                    message: err.response?.data?.detail || 'Урок недоступен.',
                    href: '/#catalog',
                    linkLabel: 'Все курсы',
                });
            } else {
                setError({ message: 'Failed to load lesson. Check console for details.' });
            }
            console.error(err);
        } finally {
            setLoading(false);
        }
    }

    async function fetchMessages() {
        if (!course) return;
        try {
            const res = await api.get(`/messages/?course=${course.id}`);
            // Merge: messages that arrived live while this loaded stay.
            setMessages(prev => mergeMessages(prev, res.data));
            setHistoryError(false);
        } catch (err) {
            console.error('Failed to load messages:', err);
            setHistoryError(true);
        }
    }

    // Socket while the window is open (reconnects by itself after a drop).
    const { status: chatStatus, send: sendChat, pending: chatPending } = useChatSocket({
        courseId: course?.id,
        otherUserId: course?.author,
        isOwn: msg => msg.sender !== course?.author,
        enabled: showChat,
        onMessage: msg => setMessages(prev => mergeMessages(prev, [msg])),
        onRejected: frame => setSendError(frame.error === 'too_long'
            ? `Сообщение не отправлено: не больше ${frame.max_length} символов.`
            : 'Сообщение не отправлено.'),
        // Server saved it: clear the input, unless the user has typed on since.
        onConfirmed: text => setNewMessage(current => (current.trim() === text ? '' : current)),
        onReconnected: fetchMessages, // pick up what was sent while offline
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

    function handleOpenChat() {
        if (!showChat) {
            setHistoryError(false);
            setSendError('');
        }
        setShowChat(!showChat);
        if (!showChat) fetchMessages();
    }

    // Close button and Esc: focus goes back to the chat button.
    function handleCloseChat() {
        setShowChat(false);
        chatButtonRef.current?.focus();
    }

    const blockNumbers = (() => {
        const map = {};
        let quizCount = 0;
        let codeCount = 0;
        let fillCount = 0;
        blocks.forEach(b => {
            if (b.type === 'QUIZ') {
                quizCount += 1;
                map[b.id] = quizCount;
            } else if (b.type === 'CODE') {
                codeCount += 1;
                map[b.id] = codeCount;
            } else if (b.type === 'FILL') {
                fillCount += 1;
                map[b.id] = fillCount;
            }
        });
        return map;
    })();

    function renderBlock(block) {
        const blockProgress = progress.find(p => p.block === block.id) || null;
        const number = blockNumbers[block.id];
        let inner = null;
        switch (block.type) {
            case 'TEXT':
                inner = <TextBlock blockId={block.id} content={block.content} />;
                break;
            case 'QUIZ':
                inner = <QuizBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number} />;
                break;
            case 'CODE':
                inner = <CodeBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number} />;
                break;
            case 'FILL':
                inner = <FillBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number} />;
                break;
            default:
                return null;
        }
        return <div key={block.id} id={`block-${block.id}`} className="lesson-anchor">{inner}</div>;
    }

    // The floating chat button (student → teacher) is hidden for the course author.
    const hasChat = Boolean(user && course && user.id !== course.author);

    if (loading) return (
        <div className="page page--narrow lesson-state">
            <p className="page-status" role="status">Loading lesson...</p>
        </div>
    );

    if (error) return (
        <div className="page page--narrow lesson-state">
            <p className="notice notice-danger" role="alert">{error.message}</p>
            {error.href && (
                // Public Django pages: plain link. In an embed, open our site in a new tab
                // instead of navigating inside the host page's iframe.
                <a className="btn btn-secondary lesson-state__link" href={error.href} {...(isInIframe ? { target: '_blank', rel: 'noopener' } : {})}>
                    {error.linkLabel}
                </a>
            )}
        </div>
    );

    return (
        <>
            <div className="page page--narrow lesson-page">

                {/* Back button — hidden when embedded in iframe (no parent SPA to go back to) */}
                {!isInIframe && course && (
                    <button
                        className="btn btn-ghost btn-sm page__back"
                        onClick={() => navigate(`/courses/${course.id}/`)}
                    >
                        ← Назад
                    </button>
                )}

                {/* Lesson header */}
                <div className="lesson-header">
                    {/* Course link — site chrome, hidden in an embed like the back button */}
                    {!isInIframe && (
                        <Link className="lesson-header__course" to={`/courses/${lesson.course}/`}>
                            {lesson.course_title}
                        </Link>
                    )}
                    <p className="lesson-header__eyebrow">Урок {lesson.order_index}</p>
                    <h1 className="lesson-header__title">{lesson.title}</h1>
                    <p className="lesson-header__meta">{blocks.length} блоков</p>
                    {(() => {
                        const taskBlocks = blocks.filter(b => TASK_TYPES.has(b.type));
                        const total = taskBlocks.length;
                        if (total === 0) return null;
                        const solved = taskBlocks.filter(b => solvedBlockIds.has(b.id)).length;
                        const percent = Math.round((solved / total) * 100);
                        const complete = solved === total;
                        return (
                            <div className={complete ? 'lesson-progress lesson-progress--complete' : 'lesson-progress'}>
                                <div className="lesson-progress__labels">
                                    <span>Решено {solved} из {total} задач</span>
                                    <span>{complete ? '✓ Урок пройден' : `${percent}%`}</span>
                                </div>
                                <div
                                    className="lesson-progress__track"
                                    role="progressbar"
                                    aria-label="Решено задач"
                                    aria-valuemin={0}
                                    aria-valuemax={total}
                                    aria-valuenow={solved}
                                >
                                    {/* Width is data, so it stays inline. */}
                                    <div className="lesson-progress__fill" style={{ width: `${percent}%` }} />
                                </div>
                            </div>
                        );
                    })()}

                    {/* Next lesson by order_index; on the last lesson, back to the course
                        ("Курс пройден" only once every task in the course is solved).
                        Always shown (no lesson locking); hidden in an embed. */}
                    {!isInIframe && (
                        <nav className="lesson-nav" aria-label="Навигация по курсу">
                            {lesson.next_lesson_id ? (
                                <Link
                                    className="btn btn-secondary btn-sm"
                                    to={`/lesson/${lesson.next_lesson_id}/`}
                                    onClick={() => window.scrollTo(0, 0)}
                                >
                                    Следующий урок →
                                </Link>
                            ) : (
                                <Link className="btn btn-secondary btn-sm" to={`/courses/${lesson.course}/`}>
                                    {lesson.course_completed ? 'Курс пройден → к курсу' : 'Последний урок → к курсу'}
                                </Link>
                            )}
                        </nav>
                    )}
                </div>

                {/* Render all blocks */}
                {blocks.map(renderBlock)}

            </div>

            {/* Floating "next task" button */}
            {firstUnresolved && (
                <button
                    className={hasChat ? 'btn btn-primary next-task-btn next-task-btn--beside-chat' : 'btn btn-primary next-task-btn'}
                    onClick={scrollToNextTask}
                    aria-label="К следующей задаче"
                    title="К следующей задаче"
                >
                    {/* Phones: only the arrow shows (a round button next to the chat). */}
                    <span className="next-task-btn__text">К следующей задаче</span>
                    <span aria-hidden="true">↓</span>
                </button>
            )}

            {/* Floating chat button — student→teacher chat. Hidden for the course
                author, who has a dedicated per-student chat on the course page. */}
            {hasChat && (
                <>
                    {showChat && (
                        <ChatPanel
                            id="lesson-chat"
                            title="Чат с учителем"
                            subtitle={course.author_name}
                            messages={messages}
                            isOwn={msg => msg.sender !== course.author}
                            emptyHint="Задайте вопрос по уроку — учитель ответит здесь."
                            status={chatStatus}
                            historyError={historyError}
                            sendError={sendError}
                            value={newMessage}
                            onChange={e => { setNewMessage(e.target.value); setSendError(''); }}
                            onSubmit={handleSendMessage}
                            sending={sendingMessage || chatPending}
                            onClose={handleCloseChat}
                        />
                    )}
                    <button
                        ref={chatButtonRef}
                        type="button"
                        className="chat-fab"
                        onClick={handleOpenChat}
                        aria-label="Чат с учителем"
                        aria-expanded={showChat}
                        aria-controls={showChat ? 'lesson-chat' : undefined}
                        title={showChat ? 'Закрыть чат' : 'Чат с учителем'}
                    >
                        {showChat ? <CloseIcon /> : <ChatIcon />}
                    </button>
                </>
            )}
        </>
    );
}

// The router reuses the component when only :lessonId changes ("Следующий
// урок →"); a key per lesson remounts it so the new lesson loads from scratch.
function LessonViewerPage() {
    const { lessonId } = useParams();
    return <LessonViewer key={lessonId} />;
}

export default LessonViewerPage;