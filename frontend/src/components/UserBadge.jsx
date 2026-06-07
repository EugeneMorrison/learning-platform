import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { logout } from '../api';

/**
 * Small fixed badge in the top-right corner showing who is logged in (like
 * Stepik's avatar menu), so the current user is visible on every page without
 * returning to the dashboard. Renders nothing if nobody is logged in.
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
        <div ref={ref} style={{ position: 'fixed', top: 12, right: 12, zIndex: 2000 }}>
            <button onClick={() => setOpen(o => !o)} style={pill} title={user.username}>
                <span style={avatar}>{initial}</span>
                <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', lineHeight: 1.15 }}>
                    <span style={{ fontWeight: 600, color: '#1e293b', fontSize: 13 }}>{user.username}</span>
                    <span style={{ fontSize: 11, color: '#64748b' }}>{roleLabel}</span>
                </span>
                <span style={{ color: '#94a3b8', fontSize: 10, marginLeft: 2 }}>▾</span>
            </button>

            {open && (
                <div style={menu}>
                    <button
                        style={menuItem}
                        onClick={() => { setOpen(false); navigate('/dashboard/'); }}
                    >
                        📊 Личный кабинет
                    </button>
                    <button style={{ ...menuItem, color: '#dc2626' }} onClick={handleLogout}>
                        Выйти
                    </button>
                </div>
            )}
        </div>
    );
}

const pill = {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '5px 10px 5px 5px',
    background: 'white',
    border: '1px solid #e2e8f0',
    borderRadius: 999,
    cursor: 'pointer',
    boxShadow: '0 1px 4px rgba(0,0,0,0.1)',
};

const avatar = {
    width: 30,
    height: 30,
    borderRadius: '50%',
    background: '#0C4B33',
    color: 'white',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 700,
    fontSize: 14,
    flexShrink: 0,
};

const menu = {
    position: 'absolute',
    top: 'calc(100% + 6px)',
    right: 0,
    minWidth: 180,
    background: 'white',
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
};

const menuItem = {
    padding: '10px 14px',
    background: 'white',
    border: 'none',
    textAlign: 'left',
    cursor: 'pointer',
    fontSize: 14,
    color: '#334155',
};

export default UserBadge;
