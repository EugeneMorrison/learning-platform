import { useImperativeHandle, useRef, useState } from 'react';
import api from '../api';
import ChatPanel, { ChatIcon, CloseIcon } from './ChatPanel';
import { MAX_MESSAGE_LENGTH, mergeMessages, messageLength, useChatSocket } from '../lib/chatSocket';
import { badgeText, useActiveChat, useUnreadCount } from '../lib/notifications';
import './Notifications.css';

/**
 * A student's chat with the course author: the floating button (with the
 * unread count for this conversation) and the floating window. Used on the
 * lesson page and on the student's course page.
 *
 * ref.open(message?): open the window (with `message` already in it, e.g. a
 * question just sent with «Задать вопрос»). While open, the conversation
 * counts as read (lib/notifications.js useActiveChat).
 */
function StudentChat({ ref, course, id, emptyHint }) {
    const [showChat, setShowChat] = useState(false);
    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [sendingMessage, setSendingMessage] = useState(false);
    const [historyError, setHistoryError] = useState(false);
    const [sendError, setSendError] = useState('');
    const buttonRef = useRef(null);
    const unread = useUnreadCount(course.id, course.author);
    useActiveChat(course.id, course.author, showChat);

    async function fetchMessages() {
        try {
            const res = await api.get(`/messages/?course=${course.id}`);
            // Merge: messages that arrived live while this loaded stay.
            setMessages(prev => mergeMessages(prev, res.data));
            setHistoryError(false);
        } catch (err) {
            console.error('Failed to load messages:', err);
            setHistoryError(true);
        }
    }

    // Socket while the window is open (reconnects by itself after a drop).
    const { status: chatStatus, send: sendChat, pending: chatPending } = useChatSocket({
        courseId: course.id,
        otherUserId: course.author,
        isOwn: msg => msg.sender !== course.author,
        enabled: showChat,
        onMessage: msg => setMessages(prev => mergeMessages(prev, [msg])),
        onRejected: frame => setSendError(frame.error === 'too_long'
            ? `Сообщение не отправлено: не больше ${frame.max_length} символов.`
            : 'Сообщение не отправлено.'),
        // Server saved it: clear the input, unless the user has typed on since.
        onConfirmed: text => setNewMessage(current => (current.trim() === text ? '' : current)),
        onReconnected: fetchMessages, // pick up what was sent while offline
    });

    function openChat() {
        setHistoryError(false);
        setSendError('');
        setShowChat(true);
        fetchMessages();
    }

    useImperativeHandle(ref, () => ({
        open(message) {
            if (message) setMessages(prev => mergeMessages(prev, [message]));
            if (!showChat) openChat();
        },
    }));

    async function handleSendMessage(e) {
        e.preventDefault();
        const text = newMessage.trim();
        if (!text || chatStatus !== 'open' || messageLength(text) > MAX_MESSAGE_LENGTH) return;
        setSendingMessage(true);
        try {
            // The input keeps the text until the server confirms it (onConfirmed).
            if (sendChat(text)) setSendError('');
        } catch (err) {
            console.error('Failed to send message:', err);
        } finally {
            setSendingMessage(false);
        }
    }

    // Close button and Esc: focus goes back to the chat button.
    function handleCloseChat() {
        setShowChat(false);
        buttonRef.current?.focus();
    }

    const label = unread > 0 ? `Чат с учителем, непрочитанных: ${unread}` : 'Чат с учителем';

    return (
        <>
            {showChat && (
                <ChatPanel
                    id={id}
                    title="Чат с учителем"
                    subtitle={course.author_name}
                    messages={messages}
                    isOwn={msg => msg.sender !== course.author}
                    emptyHint={emptyHint}
                    status={chatStatus}
                    historyError={historyError}
                    sendError={sendError}
                    value={newMessage}
                    onChange={e => { setNewMessage(e.target.value); setSendError(''); }}
                    onSubmit={handleSendMessage}
                    sending={sendingMessage || chatPending}
                    onClose={handleCloseChat}
                />
            )}
            <button
                ref={buttonRef}
                type="button"
                className="chat-fab"
                onClick={() => (showChat ? setShowChat(false) : openChat())}
                aria-label={label}
                aria-expanded={showChat}
                aria-controls={showChat ? id : undefined}
                title={showChat ? 'Закрыть чат' : label}
            >
                {showChat ? <CloseIcon /> : <ChatIcon />}
                {!showChat && unread > 0 && <span className="unread-badge" aria-hidden="true">{badgeText(unread)}</span>}
            </button>
        </>
    );
}

export default StudentChat;
