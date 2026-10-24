import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/*
 * Light / dark theme in the app, the same as on the Django pages
 * (backend/templates/public/base.html): the choice is "theme" in localStorage,
 * else the OS setting; data-theme="dark" on <html> switches tokens.css to its
 * dark values.
 *
 * The pages in THEMED_PATH have a dark theme: the dashboard, a course (its
 * page and a student's progress) and a lesson (viewer and editor). The rest
 * (login, register, enrol) stay light for now. Never inside an iframe: an
 * embedded lesson keeps the light look the host site expects. index.html
 * repeats this test in its first <script>, which sets the theme before the
 * stylesheets load: keep the two in step.
 */
export const THEME_KEY = 'theme';
const THEMED_PATH = /^\/(dashboard\/?|courses\/.+|lesson\/.+)$/;

export function isThemedPath(pathname) {
    return THEMED_PATH.test(pathname) && window.self === window.top;
}

const osDark = typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null;

export function savedTheme() {
    try {
        const theme = localStorage.getItem(THEME_KEY);
        return theme === 'light' || theme === 'dark' ? theme : null;
    } catch {
        return null; // storage blocked
    }
}

export function preferredTheme() {
    return savedTheme() || (osDark?.matches ? 'dark' : 'light');
}

export function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

let fadeTimer;

// Sets the theme on <html>; null removes it (the light, unthemed page). With
// fade, the colours change over a moment (theme-toggle.css, .theme-changing).
export function applyTheme(theme, { fade = false } = {}) {
    const root = document.documentElement;
    if (fade) {
        root.classList.add('theme-changing');
        clearTimeout(fadeTimer);
        fadeTimer = setTimeout(() => root.classList.remove('theme-changing'), 200);
    }
    if (theme) {
        root.setAttribute('data-theme', theme);
        root.style.colorScheme = theme;
    } else {
        root.removeAttribute('data-theme');
        root.style.colorScheme = '';
    }
    window.dispatchEvent(new Event('themechange'));
}

export function saveTheme(theme) {
    try {
        localStorage.setItem(THEME_KEY, theme);
    } catch {
        // storage blocked: the choice lasts until the page is left
    }
}

/**
 * In the app layout: the theme follows the route (themed pages get the saved
 * or OS theme, the rest none), and, while nothing is saved, the OS setting
 * live. A choice made in another tab applies here too.
 */
export function useRouteTheme() {
    const { pathname } = useLocation();
    const themed = isThemedPath(pathname);

    useEffect(() => {
        applyTheme(themed ? preferredTheme() : null);
        if (!themed) return undefined;

        const follow = () => { if (!savedTheme()) applyTheme(preferredTheme(), { fade: true }); };
        const fromOtherTab = e => { if (e.key === THEME_KEY) applyTheme(preferredTheme(), { fade: true }); };
        osDark?.addEventListener?.('change', follow);
        window.addEventListener('storage', fromOtherTab);
        return () => {
            osDark?.removeEventListener?.('change', follow);
            window.removeEventListener('storage', fromOtherTab);
        };
    }, [themed]);

    return themed;
}
