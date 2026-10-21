import { createContext, useContext, useEffect } from 'react';

/**
 * Unread messages for the logged-in user (components/NotificationsProvider.jsx,
 * mounted once in App.jsx): the bell in the app header, the badges on the chat
 * buttons, «Вопросы студентов» on the author's dashboard, the "(N) " title.
 *
 * Value: null when nobody is logged in (or inside an embed), else
 * { total, conversations, unreadFor(courseId, otherUserId),
 *   markRead(courseId, otherUserId), setActiveChat(courseId, otherUserId),
 *   clearActiveChat(courseId, otherUserId) }.
 * conversations: GET /api/messages/unread/ (newest first).
 */
export const NotificationsContext = createContext(null);

export function useNotifications() {
    return useContext(NotificationsContext);
}

/** Unread messages from `otherUserId` to me in this course (0 without a provider). */
export function useUnreadCount(courseId, otherUserId) {
    const notifications = useNotifications();
    return notifications && courseId && otherUserId ? notifications.unreadFor(courseId, otherUserId) : 0;
}

/**
 * A chat window with `otherUserId` in this course is open (`open`): mark it
 * read now, and mark read whatever arrives while it stays open and the tab is
 * visible (so no badge appears for messages the user is looking at).
 */
export function useActiveChat(courseId, otherUserId, open) {
    const notifications = useNotifications();
    const setActiveChat = notifications?.setActiveChat;
    const clearActiveChat = notifications?.clearActiveChat;
    useEffect(() => {
        if (!open || !courseId || !otherUserId || !setActiveChat) return undefined;
        setActiveChat(courseId, otherUserId);
        return () => clearActiveChat(courseId, otherUserId);
    }, [open, courseId, otherUserId, setActiveChat, clearActiveChat]);
}

/** Where a conversation opens: the student's chat (?chat=1) or, for the
 * course author, that student's chat on the course page (?chat=<id>). */
export function conversationLink(conversation) {
    const chat = conversation.other_is_author ? '1' : conversation.other_user_id;
    return `/courses/${conversation.course_id}/?chat=${chat}`;
}

/** "9+" above nine. */
export function badgeText(count) {
    return count > 9 ? '9+' : String(count);
}

const timeFormat = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' });
const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
});

/** "14:05" for today, "12 окт., 14:05" for older (same as the chat window). */
export function formatMessageTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    const today = new Date().toDateString() === date.toDateString();
    return (today ? timeFormat : dateTimeFormat).format(date);
}
