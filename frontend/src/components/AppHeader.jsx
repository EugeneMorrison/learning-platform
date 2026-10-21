import { useEffect, useRef } from 'react';
import { Link, useLocation, useMatch } from 'react-router-dom';
import UserBadge from './UserBadge';
import NotificationsBell from './NotificationsBell';
import LessonProgress from './LessonProgress';
import { ListIcon } from './LessonsPanel';
import BrandLogo from './BrandLogo';
import { useLessonBar } from '../lib/lessonBar';
import './AppHeader.css';

// Once every task of the lesson is solved: where the lesson leads, the same
// destination as the link after the last block (LessonViewer's nextStep).
function NextStepLink({ step }) {
    if (step.isNextLesson) {
        return (
            <Link className="app-header__next" to={step.to} onClick={() => window.scrollTo(0, 0)}>
                Следующий урок →
            </Link>
        );
    }
    return (
        <Link className="app-header__next" to={step.to}>
            {step.courseCompleted ? 'Курс пройден → к курсу' : 'К курсу →'}
        </Link>
    );
}

function readToken() {
    try {
        return localStorage.getItem('access_token');
    } catch {
        return null;
    }
}

/**
 * Minimal top bar on every app page: site name (→ landing), "Курсы" (→ landing
 * catalog) and the user badge. The landing and catalog are Django pages, so these
 * are plain links (full page load), not router links.
 *
 * On the lesson page the middle shows the lesson instead of "Курсы": the
 * "Список уроков" button, course › lesson breadcrumb (the lesson title scrolls
 * back to the top of the lesson) and "Решено X из Y задач" (once all are solved,
 * with the next-lesson link), from the data LessonViewer publishes
 * (lib/lessonBar.js). Empty until the lesson has loaded. The middle is as wide
 * as the lesson column below and lines up with it (AppHeader.css).
 *
 * Not rendered inside an iframe: an embedded lesson on a foreign site shows no
 * site chrome (same check as LessonViewer).
 */
function AppHeader() {
    // Re-render on every navigation so the badge appears right after login and
    // disappears after logout (both end with a navigate()).
    useLocation();
    const onLessonPage = useMatch('/lesson/:lessonId/');
    const lessonBar = useLessonBar();

    // The lessons panel (LessonViewer's) closed: focus back on its button.
    const lessonsButtonRef = useRef(null);
    const lessonsOpen = Boolean(lessonBar?.lessonsOpen);
    const lessonsWereOpen = useRef(false);
    useEffect(() => {
        if (lessonsWereOpen.current && !lessonsOpen) lessonsButtonRef.current?.focus();
        lessonsWereOpen.current = lessonsOpen;
    }, [lessonsOpen]);

    const isInIframe = window.self !== window.top;
    if (isInIframe) return null;

    const token = readToken();

    return (
        <header className="app-header">
            <div className={onLessonPage ? 'app-header__inner app-header__inner--lesson' : 'app-header__inner'}>
                {/* Without the badge the bar is low: the cat grows in place. */}
                <BrandLogo className="app-header__brand" compact={!token} />
                {onLessonPage ? (
                    <div className="app-header__lesson">
                        {lessonBar && (
                            <>
                                {/* Opens LessonViewer's lessons panel. */}
                                <button
                                    ref={lessonsButtonRef}
                                    type="button"
                                    className="btn btn-secondary btn-sm app-header__lessons-btn"
                                    onClick={lessonBar.onOpenLessons}
                                    aria-label="Список уроков"
                                    aria-haspopup="dialog"
                                    aria-expanded={lessonsOpen}
                                    title="Список уроков"
                                >
                                    <ListIcon />
                                </button>
                                <div className="app-header__lesson-text">
                                    <nav aria-label="Путь к уроку">
                                        <ol className="app-header__crumbs">
                                            {/* Phones: only the lesson title (the course crumb is hidden). */}
                                            <li className="app-header__crumb app-header__crumb--course">
                                                <Link
                                                    className="app-header__crumb-link"
                                                    to={`/courses/${lessonBar.courseId}/`}
                                                    title={lessonBar.courseTitle}
                                                >
                                                    {lessonBar.courseTitle}
                                                </Link>
                                            </li>
                                            <li className="app-header__crumb app-header__crumb--lesson">
                                                <span className="app-header__crumb-sep" aria-hidden="true">›</span>
                                                <button
                                                    type="button"
                                                    className="app-header__title-btn"
                                                    onClick={lessonBar.onTitleClick}
                                                    aria-current="page"
                                                    title={lessonBar.lessonTitle}
                                                >
                                                    {lessonBar.lessonTitle}
                                                    <span className="visually-hidden">, к началу урока</span>
                                                </button>
                                            </li>
                                        </ol>
                                    </nav>
                                    <LessonProgress
                                        taskIds={lessonBar.taskIds}
                                        solvedIds={lessonBar.solvedIds}
                                        completeAction={<NextStepLink step={lessonBar.nextStep} />}
                                    />
                                </div>
                            </>
                        )}
                    </div>
                ) : (
                    <nav className="app-header__nav" aria-label="Основная навигация">
                        <a className="app-header__link" href="/#catalog">Курсы</a>
                    </nav>
                )}
                {/* Bell (unread messages) and the user. Keyed by the token: a new
                    login mounts a fresh badge, which loads the new user. */}
                {token && (
                    <div className="app-header__end">
                        <NotificationsBell />
                        <UserBadge key={token} />
                    </div>
                )}
            </div>
        </header>
    );
}

export default AppHeader;
