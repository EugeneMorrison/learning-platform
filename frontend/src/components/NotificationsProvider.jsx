import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import api, { refreshAccessToken } from '../api';
import { NotificationsContext } from '../lib/notifications';

const EMPTY = { total: 0, conversations: [] };
const RETRY_FIRST_MS = 1000;
const RETRY_MAX_MS = 30000;
const CLOSE_UNAUTHORIZED = 4001;

function readToken() {
    try {
        return localStorage.getItem('access_token');
    } catch {
        return null;
    }
}

function socketUrl() {
    const token = readToken();
    const wsBase = import.meta.env.DEV
        ? 'ws://127.0.0.1:8000'
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
    return `${wsBase}/ws/notifications/?token=${encodeURIComponent(token || '')}`;
}

function sameChat(chat, courseId, otherUserId) {
    return Boolean(chat) && String(chat.courseId) === String(courseId) && String(chat.otherUserId) === String(otherUserId);
}

/**
 * Unread messages for the logged-in user (lib/notifications.js), mounted once
 * around every page (App.jsx). Loads GET /api/messages/unread/, keeps the
 * user's notification socket (ws/notifications/) open while logged in and
 * reloads the list when a message arrives or another tab reads one;
 * reconnects with a growing delay (1s … 30s, a fresh token after 4001) and
 * reloads after a reconnect, in case something arrived meanwhile.
 *
 * A message for the chat that is open (setActiveChat) while the tab is
 * visible is marked read at once instead of counted. Title: "(N) " prefix.
 */
function NotificationsProvider({ children }) {
    useLocation(); // re-check the token on every navigation (login / logout)
    const token = readToken();
    const enabled = Boolean(token) && window.self === window.top;
    const [data, setData] = useState(EMPTY);
    const activeChatRef = useRef(null);

    const refresh = useCallback(async () => {
        try {
            const res = await api.get('/messages/unread/');
            setData(res.data);
        } catch (err) {
            console.error('Failed to load unread messages:', err);
        }
    }, []);

    const markRead = useCallback(async (courseId, otherUserId) => {
        // Right away on screen; the server's answer doesn't change it.
        setData(current => {
            const conversation = current.conversations.find(c => sameChat(
                { courseId: c.course_id, otherUserId: c.other_user_id }, courseId, otherUserId));
            if (!conversation) return current;
            return {
                total: current.total - conversation.unread_count,
                conversations: current.conversations.filter(c => c !== conversation),
            };
        });
        try {
            await api.post('/messages/read/', { course_id: courseId, other_user_id: otherUserId });
        } catch (err) {
            console.error('Failed to mark messages read:', err);
            refresh();
        }
    }, [refresh]);

    const setActiveChat = useCallback((courseId, otherUserId) => {
        activeChatRef.current = { courseId, otherUserId };
        if (document.visibilityState === 'visible') markRead(courseId, otherUserId);
    }, [markRead]);

    const clearActiveChat = useCallback((courseId, otherUserId) => {
        if (sameChat(activeChatRef.current, courseId, otherUserId)) activeChatRef.current = null;
    }, []);

    // The socket, while logged in; a new one after login as someone else.
    useEffect(() => {
        if (!enabled) {
            setData(EMPTY); // eslint-disable-line react-hooks/set-state-in-effect -- logged out
            return undefined;
        }
        refresh();

        let cancelled = false;
        let socket = null;
        let timer = null;
        let attempt = 0;

        function handleEvent(event) {
            if (event.type === 'new_message') {
                const chat = activeChatRef.current;
                if (sameChat(chat, event.course_id, event.sender_id) && document.visibilityState === 'visible') {
                    markRead(event.course_id, event.sender_id); // being read right now: no badge
                    return;
                }
                refresh();
            } else if (event.type === 'read') {
                refresh(); // read in another tab
            }
        }

        function scheduleReconnect() {
            const delay = Math.min(RETRY_FIRST_MS * 2 ** attempt, RETRY_MAX_MS);
            attempt += 1;
            timer = setTimeout(connect, delay);
        }

        function connect() {
            if (cancelled) return;
            socket = new WebSocket(socketUrl());
            socket.onopen = () => {
                if (attempt > 0) refresh(); // back after a drop: catch up
                attempt = 0;
            };
            socket.onmessage = e => {
                try {
                    handleEvent(JSON.parse(e.data));
                } catch {
                    /* not JSON: ignore */
                }
            };
            socket.onclose = e => {
                if (cancelled) return;
                if (e.code === CLOSE_UNAUTHORIZED) {
                    // Expired token: get a new one, then reconnect; no refresh token → stay quiet.
                    refreshAccessToken().then(scheduleReconnect, () => {});
                    return;
                }
                scheduleReconnect();
            };
        }

        connect();
        return () => {
            cancelled = true;
            clearTimeout(timer);
            if (socket) {
                socket.onclose = null;
                socket.close();
            }
        };
    }, [enabled, token, refresh, markRead]);

    // Back to the tab with a chat open: what came meanwhile has now been seen.
    useEffect(() => {
        if (!enabled) return undefined;
        function onVisible() {
            const chat = activeChatRef.current;
            if (chat && document.visibilityState === 'visible') markRead(chat.courseId, chat.otherUserId);
        }
        document.addEventListener('visibilitychange', onVisible);
        return () => document.removeEventListener('visibilitychange', onVisible);
    }, [enabled, markRead]);

    // "(N) " in front of the page title while anything is unread.
    useEffect(() => {
        const base = document.title.replace(/^\(\d+\) /, '');
        document.title = data.total > 0 ? `(${data.total}) ${base}` : base;
    }, [data.total]);

    const value = useMemo(() => (enabled ? {
        total: data.total,
        conversations: data.conversations,
        unreadFor: (courseId, otherUserId) => data.conversations.find(c => sameChat(
            { courseId: c.course_id, otherUserId: c.other_user_id }, courseId, otherUserId))?.unread_count || 0,
        markRead,
        setActiveChat,
        clearActiveChat,
    } : null), [enabled, data, markRead, setActiveChat, clearActiveChat]);

    return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>;
}

export default NotificationsProvider;
