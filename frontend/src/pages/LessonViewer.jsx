import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { getLesson, getBlocks } from '../api';
import api from '../api';
import TextBlock from '../components/TextBlock';
import QuizBlock from '../components/QuizBlock';
import CodeBlock from '../components/CodeBlock';
import FillBlock from '../components/FillBlock';
import LessonsPanel from '../components/LessonsPanel';
import ChatPanel, { ChatIcon, CloseIcon } from '../components/ChatPanel';
import LessonProgress from '../components/LessonProgress';
import { watchFigureOverflow } from '../lib/contentImages';
import { useSetLessonBar } from '../lib/lessonBar';
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

// Where the lesson leads: the next lesson in the course or, on the last lesson,
// back to the course (courseCompleted: every task in the course is solved).
// One rule for the link after the last block and the app header's link.
function nextStep(lesson) {
    return lesson.next_lesson_id
        ? { to: `/lesson/${lesson.next_lesson_id}/`, isNextLesson: true }
        : { to: `/courses/${lesson.course}/`, isNextLesson: false, courseCompleted: lesson.course_completed };
}

function LessonViewer() {
    const isInIframe = window.self !== window.top;
    const { hash } = useLocation();

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
    const [showLessons, setShowLessons] = useState(false);
    const chatButtonRef = useRef(null);
    const codeRefetchSeq = useRef({}); // block id → number of its latest read-back

    // The one source of truth for "solved" on this page (is_correct, as in the
    // lessons panel and course_completed). The app header counts X from it.
    const solvedBlockIds = useMemo(
        () => new Set(progress.filter(p => p.is_correct === true).map(p => p.block)),
        [progress]
    );
    const taskIds = useMemo(
        () => blocks.filter(b => TASK_TYPES.has(b.type)).map(b => b.id),
        [blocks]
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

    // Last lesson: course_completed was loaded with the page. When the student
    // completes this lesson here, re-read the lesson so both "… к курсу" links
    // (nextStep) show whether the whole course is now done.
    const lessonComplete = taskIds.length > 0 && taskIds.every(id => solvedBlockIds.has(id));
    const lessonWasComplete = useRef(null); // null until the page has loaded
    useEffect(() => {
        if (loading || !lesson) return;
        const was = lessonWasComplete.current;
        lessonWasComplete.current = lessonComplete;
        if (was === false && lessonComplete && !lesson.next_lesson_id && !lesson.course_completed) {
            getLesson(lesson.id)
                .then(res => setLesson(res.data))
                .catch(err => console.error('Failed to reload the lesson:', err));
        }
    }, [loading, lesson, lessonComplete]);

    // The app header's lessons button opens this page's lessons panel.
    const openLessons = useCallback(() => setShowLessons(true), []);

    // The lesson title in the app header: back to the top of the lesson content,
    // with the blocks' own scroll offset (.lesson-anchor), so nothing ends up
    // under the app header.
    const scrollToContent = useCallback(() => {
        const first = blocks[0] && document.getElementById(`block-${blocks[0].id}`);
        if (first) first.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else window.scrollTo({ top: 0, behavior: 'smooth' });
    }, [blocks]);

    // The app header shows the breadcrumb and progress once everything has
    // loaded (not "Решено 0 из N" before the progress arrives); cleared when
    // leaving the page.
    const setLessonBar = useSetLessonBar();
    useEffect(() => {
        if (loading || error || !lesson) return undefined;
        setLessonBar({
            courseId: lesson.course,
            courseTitle: lesson.course_title,
            lessonTitle: lesson.title,
            taskIds,
            solvedIds: solvedBlockIds,
            nextStep: nextStep(lesson),
            lessonsOpen: showLessons,
            onOpenLessons: openLessons,
            onTitleClick: scrollToContent,
        });
        return () => setLessonBar(null);
    }, [loading, error, lesson, taskIds, solvedBlockIds, showLessons, openLessons, scrollToContent, setLessonBar]);

    // Fade at the right edge of formula boxes that scroll sideways (phones).
    useEffect(() => {
        if (loading) return undefined;
        return watchFigureOverflow(document.querySelector('.lesson-page'));
    }, [loading, blocks]);

    // "#block-<id>" (e.g. back from the editor): the browser's own hash scroll
    // fires before the blocks have loaded, so scroll once they are on the page.
    useEffect(() => {
        if (loading || !hash.startsWith('#block-')) return;
        const el = document.getElementById(hash.slice(1));
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, [loading, hash]);

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

    // After a submission, the block's stored progress record replaces the old
    // one; everything that reads solvedBlockIds (app header, "next task", the
    // embed card) follows. Only a recorded submission changes what is stored:
    // the server grades a re-submission of an already solved block (that block
    // stays solved) but doesn't save it, and then its response is this
    // attempt's result, not the stored record.
    function storeProgressRecord(record) {
        setProgress(prev => [...prev.filter(p => p.block !== record.block), record]);
    }

    // QUIZ / FILL: /progress/submit/ returns the saved record (+ "recorded").
    function handleAnswerSubmitted(data) {
        if (!data.recorded) return;
        const record = { ...data };
        delete record.recorded;
        storeProgressRecord(record);
    }

    // CODE: /run-tests/ returns the test results and is_correct, not the saved
    // record, so read the record back. Only this block's record is taken (the
    // others may have changed since), and only from the latest read-back.
    async function handleCodeSubmitted(blockId, data) {
        if (!data.recorded) return;
        const seq = (codeRefetchSeq.current[blockId] || 0) + 1;
        codeRefetchSeq.current[blockId] = seq;
        try {
            const res = await api.get(`/progress/course/${lesson.course}/`);
            const record = res.data.find(p => p.block === blockId);
            if (record && codeRefetchSeq.current[blockId] === seq) storeProgressRecord(record);
        } catch (err) {
            console.error('Failed to reload progress:', err);
        }
    }

    function renderBlock(block) {
        const blockProgress = progress.find(p => p.block === block.id) || null;
        const number = blockNumbers[block.id];
        let inner = null;
        switch (block.type) {
            case 'TEXT':
                inner = <TextBlock blockId={block.id} content={block.content} />;
                break;
            case 'QUIZ':
                inner = <QuizBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number}
                    onSubmitted={handleAnswerSubmitted} />;
                break;
            case 'CODE':
                inner = <CodeBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number}
                    onSubmitted={data => handleCodeSubmitted(block.id, data)} />;
                break;
            case 'FILL':
                inner = <FillBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number}
                    onSubmitted={handleAnswerSubmitted} />;
                break;
            default:
                return null;
        }
        return (
            <div key={block.id} id={`block-${block.id}`} className="lesson-anchor">
                {canEdit && (
                    <div className="lesson-anchor__tools">
                        <Link className="btn btn-secondary btn-sm" to={`/lesson/${lesson.id}/edit/?block=${block.id}`}>
                            ✎ Изменить
                        </Link>
                    </div>
                )}
                {inner}
            </div>
        );
    }

    // Lessons panel: Esc, backdrop, close button or a chosen lesson close it;
    // the app header then puts focus back on its "Список уроков" button.
    function handleCloseLessons() {
        setShowLessons(false);
    }

    // The course's author: edit buttons instead of the student chat.
    const isCourseAuthor = Boolean(user && course && user.id === course.author);
    // "✎ Редактировать урок" / "✎ Изменить": the author only, never in an embed.
    const canEdit = isCourseAuthor && !isInIframe;
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

                {/* The lessons button, lesson title and progress are in the app
                    header. Here, for the author only: "✎ Редактировать урок" (no
                    row at all for students; never in an embed, see canEdit). */}
                {canEdit && (
                    <div className="lesson-toolbar">
                        <Link
                            className="btn btn-secondary btn-sm lesson-toolbar__edit"
                            to={`/lesson/${lesson.id}/edit/`}
                            onClick={() => window.scrollTo(0, 0)}
                        >
                            ✎ Редактировать урок
                        </Link>
                    </div>
                )}

                {/* An embed has no app header: title and progress stay on the page. */}
                {isInIframe && (
                    <div className="lesson-header">
                        <h1 className="lesson-header__title">{lesson.title}</h1>
                        <LessonProgress taskIds={taskIds} solvedIds={solvedBlockIds} />
                    </div>
                )}

                {showLessons && (
                    <LessonsPanel
                        courseId={lesson.course}
                        courseTitle={lesson.course_title}
                        currentLessonId={lesson.id}
                        onClose={handleCloseLessons}
                    />
                )}

                {/* Render all blocks */}
                {blocks.map(renderBlock)}

                {/* After the last block: the next lesson in the course; on the last
                    lesson, back to the course ("Курс пройден" only once every task in
                    the course is solved). Always shown (no lesson locking); hidden
                    in an embed. */}
                {!isInIframe && (() => {
                    const step = nextStep(lesson);
                    return (
                        <nav className="lesson-nav" aria-label="Навигация по курсу">
                            {step.isNextLesson ? (
                                <Link
                                    className="btn btn-secondary btn-sm"
                                    to={step.to}
                                    onClick={() => window.scrollTo(0, 0)}
                                >
                                    Следующий урок →
                                </Link>
                            ) : (
                                <Link className="btn btn-secondary btn-sm" to={step.to}>
                                    {step.courseCompleted ? 'Курс пройден → к курсу' : 'Последний урок → к курсу'}
                                </Link>
                            )}
                        </nav>
                    );
                })()}

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