import { Link, useLocation, useMatch } from 'react-router-dom';
import UserBadge from './UserBadge';
import LessonProgress from './LessonProgress';
import { BRAND_NAME } from '../brand';
import { useLessonBar } from '../lib/lessonBar';
import './AppHeader.css';

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
 * On the lesson page the middle shows the lesson instead of "Курсы": course ›
 * lesson breadcrumb and "Решено X из Y задач", from the data LessonViewer
 * publishes (lib/lessonBar.js). Empty until the lesson has loaded.
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
    const isInIframe = window.self !== window.top;
    if (isInIframe) return null;

    const token = readToken();

    return (
        <header className="app-header">
            <div className="app-header__inner">
                <a className="app-header__brand" href="/">{BRAND_NAME}</a>
                {onLessonPage ? (
                    <div className="app-header__lesson">
                        {lessonBar && (
                            <>
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
                                        <li className="app-header__crumb app-header__crumb--lesson" aria-current="page" title={lessonBar.lessonTitle}>
                                            <span className="app-header__crumb-sep" aria-hidden="true">›</span>
                                            {lessonBar.lessonTitle}
                                        </li>
                                    </ol>
                                </nav>
                                <LessonProgress taskIds={lessonBar.taskIds} solvedIds={lessonBar.solvedIds} />
                            </>
                        )}
                    </div>
                ) : (
                    <nav className="app-header__nav" aria-label="Основная навигация">
                        <a className="app-header__link" href="/#catalog">Курсы</a>
                    </nav>
                )}
                {/* Keyed by the token: a new login mounts a fresh badge, which loads the new user. */}
                {token && <UserBadge key={token} />}
            </div>
        </header>
    );
}

export default AppHeader;
