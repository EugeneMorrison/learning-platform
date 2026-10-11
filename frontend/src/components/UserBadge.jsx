import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
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
    const [fetchedUser, setFetchedUser] = useState(null);
    const [open, setOpen] = useState(false);
    const ref = useRef(null);

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
        logout();
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
