import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { getLesson, getBlocks } from '../api';
import api from '../api';
import TextBlock from '../components/TextBlock';
import QuizBlock from '../components/QuizBlock';
import CodeBlock from '../components/CodeBlock';
import FillBlock from '../components/FillBlock';
import LessonsPanel from '../components/LessonsPanel';
import StudentChat from '../components/StudentChat';
import QuestionModal from '../components/QuestionModal';
import LessonProgress from '../components/LessonProgress';
import DiscussionPanel from '../components/DiscussionPanel';
import { watchFigureOverflow } from '../lib/contentImages';
import { useSetLessonBar } from '../lib/lessonBar';
import './LessonViewer.css';

// Block types that are solvable tasks (have a pass/fail, count toward progress).
const TASK_TYPES = new Set(['QUIZ', 'CODE', 'FILL']);

// Task names as on the blocks' badges ("Задача 2"), for the discussion panel.
const TASK_LABELS = { CODE: 'Задача', QUIZ: 'Тест', FILL: 'Пропуски' };
const DISCUSSION_PANEL_ID = 'lesson-discussion';

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
    const { hash, search } = useLocation();

    const [lesson, setLesson] = useState(null);
    const [blocks, setBlocks] = useState([]);
    const [course, setCourse] = useState(null);
    const [user, setUser] = useState(null);
    const [progress, setProgress] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showLessons, setShowLessons] = useState(false);
    // «Задать вопрос» open for this task: { blockId, draft? } (draft: CODE editor code).
    const [question, setQuestion] = useState(null);
    const chatRef = useRef(null); // StudentChat: open(message?), close()
    // The task whose discussion is open (one at a time), «💬 N» per task and,
    // for the course author, open reports per task.
    const [discussionBlockId, setDiscussionBlockId] = useState(null);
    const [discussionCounts, setDiscussionCounts] = useState({});
    const [discussionReports, setDiscussionReports] = useState({});
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
        let active = true;
        loadLesson(() => active);
        return () => { active = false; };
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

    // «💬 N»: threads this user may read, per task. Again after a solve (a
    // solved task shows every thread) and when the panel starts or deletes one.
    // No discussions in an embed.
    const discussionsOn = Boolean(user) && !isInIframe;
    const lessonId = lesson?.id;
    const loadDiscussionCounts = useCallback(() => {
        if (!lessonId) return;
        api.get('/discussions/counts/', { params: { lesson: lessonId } })
            .then(res => {
                setDiscussionCounts(res.data.counts);
                setDiscussionReports(res.data.reports || {});
            })
            .catch(err => console.error('Failed to load discussion counts:', err));
    }, [lessonId]);
    // Changes only when a task becomes solved, not on every submission.
    const solvedKey = [...solvedBlockIds].sort().join(',');
    useEffect(() => {
        if (!loading && discussionsOn) loadDiscussionCounts();
    }, [loading, discussionsOn, loadDiscussionCounts, solvedKey]);

    // "?discussion=<block id>" (a report on the author's dashboard): open that
    // task's discussion once the lesson is on the page.
    const discussionParam = new URLSearchParams(search).get('discussion');
    useEffect(() => {
        if (loading || !discussionsOn || !discussionParam) return;
        if (blocks.some(b => b.id === discussionParam && TASK_TYPES.has(b.type))) {
            setDiscussionBlockId(discussionParam);
        }
    }, [loading, discussionsOn, discussionParam, blocks]);

    // Fade at the right edge of formula boxes that scroll sideways (phones).
    useEffect(() => {
        if (loading) return undefined;
        return watchFigureOverflow(document.querySelector('.lesson-page'));
    }, [loading, blocks]);

    // "#block-<id>" (back from the editor, «Открыть задание» on a question in
    // the chat): the browser's own hash scroll fires before the blocks have
    // loaded, so scroll once they are on the page, then briefly highlight it.
    useEffect(() => {
        if (loading || !hash.startsWith('#block-')) return undefined;
        const el = document.getElementById(hash.slice(1));
        if (!el) return undefined;
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        el.classList.add('lesson-anchor--flash');
        const timer = setTimeout(() => el.classList.remove('lesson-anchor--flash'), 2000);
        return () => {
            clearTimeout(timer);
            el.classList.remove('lesson-anchor--flash');
        };
    }, [loading, hash]);

    async function loadLesson(isActive) {
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
            if (!isActive()) return;
            const courseResponse = await api.get(`/courses/${lessonResponse.data.course}/`);
            let loadedUser = null;
            try {
                const userResponse = await api.get('/auth/me/');
                loadedUser = userResponse.data;
            } catch {
                // User decoration is optional; saved task state is not.
            }
            const progressResponse = await api.get(`/progress/course/${lessonResponse.data.course}/`);
            if (!isActive()) return;
            // Mount tasks only with the matching saved progress. QuizBlock's
            // initial state is restored once, when it mounts.
            setLesson(lessonResponse.data);
            setBlocks(blocksResponse.data);
            setCourse(courseResponse.data);
            setUser(loadedUser);
            setProgress(progressResponse.data);
        } catch (err) {
            if (!isActive()) return;
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
                setError({ message: 'Не удалось загрузить урок и сохранённые ответы. Обновите страницу, чтобы повторить попытку.' });
            }
            console.error(err);
        } finally {
            if (isActive()) setLoading(false);
        }
    }

    // «Задать вопрос» sent: the dialog closes and the chat opens with the
    // question in it (also arriving over the socket; merged by id).
    function handleQuestionSent(message) {
        setQuestion(null);
        chatRef.current?.open(message);
    }

    // One panel on the right at a time: the discussion closes the chat window,
    // and the chat (StudentChat onOpen) closes the discussion.
    function toggleDiscussion(blockId) {
        if (discussionBlockId === blockId) {
            closeDiscussion();
            return;
        }
        chatRef.current?.close();
        setDiscussionBlockId(blockId);
    }

    // Focus goes back to the block's «💬 N».
    function closeDiscussion() {
        const badge = document.getElementById(`discuss-${discussionBlockId}`);
        setDiscussionBlockId(null);
        badge?.focus();
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
    // The verdict is already known, so the task counts as solved right away:
    // waiting for the read-back left "К следующей задаче" (and the header's
    // count) pointing at the task just solved until it arrived.
    async function handleCodeSubmitted(blockId, data) {
        if (!data.recorded) return;
        setProgress(prev => {
            const old = prev.find(p => p.block === blockId);
            return [...prev.filter(p => p.block !== blockId),
                { ...old, block: blockId, lesson: lesson.id, is_correct: data.is_correct === true }];
        });
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
        const discussion = discussionsOn ? {
            count: discussionCounts[block.id] || 0,
            reports: discussionReports[block.id] || 0,
            open: discussionBlockId === block.id,
            onToggle: () => toggleDiscussion(block.id),
            panelId: DISCUSSION_PANEL_ID,
        } : undefined;
        let inner = null;
        switch (block.type) {
            case 'TEXT':
                inner = <TextBlock blockId={block.id} content={block.content} />;
                break;
            case 'QUIZ':
                inner = <QuizBlock blockId={block.id} quizRevision={block.updated_at} content={block.content} savedProgress={blockProgress} number={number}
                    onSubmitted={handleAnswerSubmitted} discussion={discussion}
                    onAsk={hasChat ? () => setQuestion({ blockId: block.id }) : undefined} />;
                break;
            case 'CODE':
                inner = <CodeBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number}
                    onSubmitted={data => handleCodeSubmitted(block.id, data)} discussion={discussion}
                    onAsk={hasChat ? draft => setQuestion({ blockId: block.id, draft }) : undefined} />;
                break;
            case 'FILL':
                inner = <FillBlock blockId={block.id} content={block.content} savedProgress={blockProgress} number={number}
                    onSubmitted={handleAnswerSubmitted} discussion={discussion}
                    onAsk={hasChat ? () => setQuestion({ blockId: block.id }) : undefined} />;
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

    const discussionBlock = discussionsOn && blocks.find(b => b.id === discussionBlockId);

    // .lesson-viewer--discussion: room for the docked panel, the floating
    // buttons moved or hidden (LessonViewer.css).
    return (
        <div className={discussionBlock ? 'lesson-viewer lesson-viewer--discussion' : 'lesson-viewer'}>
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

                {/* «Задать вопрос» (students: same people as the chat). */}
                {question && (
                    <QuestionModal
                        blockId={question.blockId}
                        draft={question.draft}
                        onClose={() => setQuestion(null)}
                        onSent={handleQuestionSent}
                    />
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

            {/* Floating chat button — student→teacher chat (StudentChat). Hidden for
                the course author, who has a per-student chat on the course page. */}
            {hasChat && (
                <StudentChat
                    ref={chatRef}
                    course={course}
                    id="lesson-chat"
                    emptyHint="Задайте вопрос по уроку — учитель ответит здесь."
                    onOpen={() => setDiscussionBlockId(null)}
                />
            )}

            {/* The open task's public discussion (right panel / bottom sheet). */}
            {discussionBlock && (
                <DiscussionPanel
                    key={discussionBlock.id}
                    id={DISCUSSION_PANEL_ID}
                    blockId={discussionBlock.id}
                    title={`${TASK_LABELS[discussionBlock.type]} ${blockNumbers[discussionBlock.id]}`}
                    solved={solvedBlockIds.has(discussionBlock.id)}
                    onClose={closeDiscussion}
                    onThreadsChanged={loadDiscussionCounts}
                />
            )}
        </div>
    );
}

// The router reuses the component when only :lessonId changes ("Следующий
// урок →"); a key per lesson remounts it so the new lesson loads from scratch.
function LessonViewerPage() {
    const { lessonId } = useParams();
    return <LessonViewer key={lessonId} />;
}

export default LessonViewerPage;
