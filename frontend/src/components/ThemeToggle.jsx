import { useEffect, useState } from 'react';
import { applyTheme, currentTheme, saveTheme } from '../lib/theme';

/**
 * Light / dark switch in the app bar, on the pages that have a dark theme
 * (lib/theme.js). The same markup and styles as the Django header's switch
 * (backend/static/public/css/theme-toggle.css, linked by vite.config.js) and
 * the same saved choice, so both sides of the site agree.
 */
function ThemeToggle() {
    const [theme, setTheme] = useState(currentTheme);

    // The theme can also change without a click here (the OS, another tab).
    useEffect(() => {
        const sync = () => setTheme(currentTheme());
        window.addEventListener('themechange', sync);
        return () => window.removeEventListener('themechange', sync);
    }, []);

    const label = theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему';

    function toggle() {
        const next = theme === 'dark' ? 'light' : 'dark';
        saveTheme(next);
        applyTheme(next, { fade: true });
    }

    return (
        <button type="button" className="theme-toggle" onClick={toggle} aria-label={label} title={label}>
            <span className="theme-toggle__knob" aria-hidden="true" />
            <svg className="theme-toggle__icon theme-toggle__sun" width="16" height="16" viewBox="0 0 24 24"
                aria-hidden="true" focusable="false">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <svg className="theme-toggle__icon theme-toggle__moon" width="16" height="16" viewBox="0 0 24 24"
                aria-hidden="true" focusable="false">
                <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
            </svg>
        </button>
    );
}

export default ThemeToggle;
