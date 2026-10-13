import { useEffect, useRef, useState } from 'react';
import { refreshAccessToken } from '../api';

// Chat WebSocket shared by the lesson page (student → teacher) and the course
// page (teacher → one student). Server side: api/consumers.py.

// Same limit as the server (api/chat.py MAX_MESSAGE_LENGTH).
export const MAX_MESSAGE_LENGTH = 2000;

// Length in characters as the server counts them (code points, so an emoji is 1).
export function messageLength(text) {
    return [...text].length;
}

// History and live messages in one list: no duplicates (by id), oldest first.
export function mergeMessages(current, incoming) {
    const byId = new Map(current.map(m => [m.id, m]));
    incoming.forEach(m => byId.set(m.id, m));
    return [...byId.values()].sort((a, b) =>
        String(a.created_at).localeCompare(String(b.created_at)) || a.id - b.id);
}

const RETRY_FIRST_MS = 1000;
const RETRY_MAX_MS = 30000;
const CLOSE_UNAUTHORIZED = 4001; // token missing / expired
const CLOSE_FORBIDDEN = 4003;    // not a participant: retrying will not help

function socketUrl(courseId, otherUserId) {
    const token = localStorage.getItem('access_token');
    const wsBase = import.meta.env.DEV
        ? 'ws://127.0.0.1:8000'
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
    return `${wsBase}/ws/chat/${courseId}/${otherUserId}/?token=${encodeURIComponent(token || '')}`;
}

/*
 * Keeps a socket open while `enabled`. After a drop it reconnects with a
 * growing delay (1s, 2s, 4s … 30s), getting a fresh access token first, and
 * calls onReconnected so the page can re-fetch the history it may have missed.
 *
 * status: 'connecting' | 'open' | 'reconnecting'
 *       | 'forbidden' (not allowed in this chat) | 'session' (log in again)
 * Handlers: onMessage(message), onRejected(frame) for {"error": ...} frames,
 * onReconnected(), onConfirmed(text).
 *
 * A sent text stays "pending" until the server echoes it back as one of our
 * own messages (isOwn(message)): then onConfirmed(text) lets the page clear
 * the input. A rejection or a dropped connection ends it without
 * confirmation, so the text stays in the input to fix or send again.
 */
export function useChatSocket({
    courseId, otherUserId, enabled, isOwn, onMessage, onRejected, onReconnected, onConfirmed,
}) {
    const [status, setStatus] = useState('connecting');
    const [pending, setPending] = useState(false);
    const socketRef = useRef(null);
    const pendingTextRef = useRef(null);
    const handlersRef = useRef({});

    useEffect(() => {
        handlersRef.current = { isOwn, onMessage, onRejected, onReconnected, onConfirmed };
    });

    function settlePending() {
        const text = pendingTextRef.current;
        pendingTextRef.current = null;
        setPending(false);
        return text;
    }

    useEffect(() => {
        if (!enabled || !courseId || !otherUserId) return undefined;

        let cancelled = false;
        let attempt = 0;
        let timer = null;
        let opened = false;        // a socket of this session has opened before
        let lastUnauthorized = false;

        function connect() {
            timer = null;
            const socket = new WebSocket(socketUrl(courseId, otherUserId));
            socketRef.current = socket;

            socket.onopen = () => {
                if (socketRef.current !== socket) return;
                attempt = 0;
                lastUnauthorized = false;
                setStatus('open');
                if (opened) handlersRef.current.onReconnected?.();
                opened = true;
            };

            socket.onmessage = (event) => {
                if (socketRef.current !== socket) return;
                let frame;
                try {
                    frame = JSON.parse(event.data);
                } catch (err) {
                    console.error('Bad chat message payload:', err);
                    return;
                }
                const handlers = handlersRef.current;
                if (frame && frame.error) {
                    settlePending(); // the text stays in the input
                    handlers.onRejected?.(frame);
                    return;
                }
                handlers.onMessage?.(frame);
                if (pendingTextRef.current !== null && handlers.isOwn?.(frame)
                    && frame.text === pendingTextRef.current) {
                    handlers.onConfirmed?.(settlePending());
                }
            };

            socket.onerror = (err) => {
                console.error('Chat socket error:', err);
            };

            socket.onclose = (event) => {
                if (cancelled || socketRef.current !== socket) return;
                socketRef.current = null;
                settlePending(); // unconfirmed: keep the text
                if (event.code === CLOSE_FORBIDDEN) {
                    setStatus('forbidden');
                    return;
                }
                // Refused twice in a row even with a fresh token: stop.
                if (event.code === CLOSE_UNAUTHORIZED && lastUnauthorized) {
                    setStatus('session');
                    return;
                }
                lastUnauthorized = event.code === CLOSE_UNAUTHORIZED;
                setStatus('reconnecting');
                // An expired token is fixed by the refresh: retry at once.
                const delay = lastUnauthorized ? 0 : Math.min(RETRY_MAX_MS, RETRY_FIRST_MS * 2 ** attempt);
                attempt += 1;
                timer = setTimeout(reconnect, delay);
            };
        }

        async function reconnect() {
            timer = null;
            try {
                await refreshAccessToken();
            } catch (err) {
                // No refresh token, or the server refused it: the user must log in.
                // A network error (no response) falls through: the connection
                // attempt fails too and the next retry is scheduled.
                if (err.response || !localStorage.getItem('refresh_token')) {
                    if (!cancelled) setStatus('session');
                    return;
                }
            }
            if (!cancelled) connect();
        }

        // Back online: don't wait for the rest of the delay.
        function handleOnline() {
            if (timer !== null) {
                clearTimeout(timer);
                reconnect();
            }
        }

        connect();
        window.addEventListener('online', handleOnline);

        return () => {
            cancelled = true;
            window.removeEventListener('online', handleOnline);
            if (timer !== null) clearTimeout(timer);
            const socket = socketRef.current;
            socketRef.current = null;
            if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
                socket.close();
            }
            setStatus('connecting'); // what the window shows when it opens next
            pendingTextRef.current = null;
            setPending(false);
        };
    }, [enabled, courseId, otherUserId]);

    // True when the text went out on an open socket (it is then pending).
    // Send it trimmed: the server echoes the trimmed text.
    function send(text) {
        const socket = socketRef.current;
        if (!socket || socket.readyState !== WebSocket.OPEN || pendingTextRef.current !== null) return false;
        socket.send(JSON.stringify({ text }));
        pendingTextRef.current = text;
        setPending(true);
        return true;
    }

    return { status, send, pending };
}
