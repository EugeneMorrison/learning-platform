import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import api, { logout } from '../api';
import './UserBadge.css';

/**
 * Badge in the app header showing who is logged in (like Stepik's avatar menu),
 * so the current user is visible on every page without returning to the
 * dashboard. Renders nothing if nobody is logged in.
 *
 * Pass `user` if the page already has it (avoids a duplicate /auth/me/ call);
 * otherwise the badge fetches it itself.
 */
function UserBadge({ user: userProp }) {
    const navigate = useNavigate();
    const location = useLocation();
    const [fetchedUser, setFetchedUser] = useState(null);
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    // «Выйти» clicked: the location key it was clicked on, until the next navigation.
    const logoutFromRef = useRef(null);

    // Log out only once the router has really reached /login/. A page may
    // block leaving (the lesson editor with unsaved changes); if the author
    // stays, she must stay logged in, so «Сохранить» still works.
    useEffect(() => {
        const from = logoutFromRef.current;
        if (from === null || location.key === from) return;
        logoutFromRef.current = null;
        if (location.pathname === '/login/') {
            logout();
            // Hide the badge right away: the header re-renders only on the next
            // navigation, and the tokens it reads are gone now.
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setFetchedUser(null);
        }
    }, [location]);

    // Only fetch when the page didn't already hand us a user.
    useEffect(() => {
        if (userProp) return;
        let active = true;
        api.get('/auth/me/')
            .then(res => { if (active) setFetchedUser(res.data); })
            .catch(() => { /* not logged in — badge stays hidden */ });
        return () => { active = false; };
    }, [userProp]);

    const user = userProp || fetchedUser;

    // Close the dropdown when clicking outside it.
    useEffect(() => {
        function onClick(e) {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        }
        document.addEventListener('mousedown', onClick);
        return () => document.removeEventListener('mousedown', onClick);
    }, []);

    if (!user) return null;

    const initial = (user.username?.[0] || '?').toUpperCase();
    const roleLabel = user.role === 'AUTHOR' ? 'Автор' : user.role === 'ADMIN' ? 'Админ' : 'Студент';

    function handleLogout() {
        setOpen(false);
        logoutFromRef.current = location.key;
        navigate('/login/');
    }

    return (
        <div ref={ref} className="user-badge">
            <button
                className="user-badge__pill"
                onClick={() => setOpen(o => !o)}
                title={user.username}
                aria-haspopup="menu"
                aria-expanded={open}
            >
                <span className="user-badge__avatar" aria-hidden="true">{initial}</span>
                <span className="user-badge__text">
                    <span className="user-badge__name">{user.username}</span>
                    <span className="user-badge__role">{roleLabel}</span>
                </span>
                <span className="user-badge__caret" aria-hidden="true">▾</span>
            </button>

            {open && (
                <div className="user-badge__menu" role="menu">
                    <button
                        className="user-badge__item"
                        role="menuitem"
                        onClick={() => { setOpen(false); navigate('/dashboard/'); }}
                    >
                        📊 Личный кабинет
                    </button>
                    <button className="user-badge__item user-badge__item--danger" role="menuitem" onClick={handleLogout}>
                        Выйти
                    </button>
                </div>
            )}
        </div>
    );
}

export default UserBadge;
