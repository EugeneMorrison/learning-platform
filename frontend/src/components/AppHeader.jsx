import { useLocation } from 'react-router-dom';
import UserBadge from './UserBadge';
import { BRAND_NAME } from '../brand';
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
 * Not rendered inside an iframe: an embedded lesson on a foreign site shows no
 * site chrome (same check as LessonViewer).
 */
function AppHeader() {
    // Re-render on every navigation so the badge appears right after login and
    // disappears after logout (both end with a navigate()).
    useLocation();
    const isInIframe = window.self !== window.top;
    if (isInIframe) return null;

    const token = readToken();

    return (
        <header className="app-header">
            <div className="app-header__inner">
                <a className="app-header__brand" href="/">{BRAND_NAME}</a>
                <nav className="app-header__nav" aria-label="Основная навигация">
                    <a className="app-header__link" href="/#catalog">Курсы</a>
                </nav>
                {/* Keyed by the token: a new login mounts a fresh badge, which loads the new user. */}
                {token && <UserBadge key={token} />}
            </div>
        </header>
    );
}

export default AppHeader;
