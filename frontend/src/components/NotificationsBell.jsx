import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { badgeText, conversationLink, formatMessageTime, useNotifications } from '../lib/notifications';
import './Notifications.css';

function BellIcon() {
    return (
        <svg className="notify-bell__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20a2 2 0 0 0 4 0" />
        </svg>
    );
}

/**
 * The app header's bell: unread count (hidden at 0, "9+" above nine) and a
 * dropdown of the conversations with unread messages; choosing one opens that
 * chat (lib/notifications.js conversationLink). Outside click and Esc close it.
 */
function NotificationsBell() {
    const notifications = useNotifications();
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const buttonRef = useRef(null);

    useEffect(() => {
        if (!open) return undefined;
        function onPointer(e) {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        }
        function onKey(e) {
            if (e.key === 'Escape') {
                setOpen(false);
                buttonRef.current?.focus();
            }
        }
        document.addEventListener('mousedown', onPointer);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onPointer);
            document.removeEventListener('keydown', onKey);
        };
    }, [open]);

    if (!notifications) return null;
    const { total, conversations } = notifications;
    const label = total > 0 ? `Сообщения: непрочитанных ${total}` : 'Сообщения: новых нет';

    return (
        <div ref={ref} className="notify-bell">
            <button
                ref={buttonRef}
                type="button"
                className="notify-bell__button"
                onClick={() => setOpen(o => !o)}
                aria-label={label}
                title={label}
                aria-expanded={open}
                aria-controls={open ? 'notify-menu' : undefined}
            >
                <BellIcon />
                {total > 0 && <span className="unread-badge notify-bell__badge" aria-hidden="true">{badgeText(total)}</span>}
            </button>

            {open && (
                <div id="notify-menu" className="notify-menu">
                    <p className="notify-menu__title">Новые сообщения</p>
                    {conversations.length === 0 ? (
                        <p className="notify-menu__empty">Новых сообщений нет.</p>
                    ) : (
                        <ul className="notify-menu__list">
                            {conversations.map(c => (
                                <li key={`${c.course_id}:${c.other_user_id}`}>
                                    <Link className="notify-item" to={conversationLink(c)} onClick={() => setOpen(false)}>
                                        <span className="notify-item__top">
                                            <span className="notify-item__who">
                                                {c.course_title} › {c.other_user_name}
                                            </span>
                                            <span className="unread-badge" aria-label={`непрочитанных: ${c.unread_count}`}>
                                                {badgeText(c.unread_count)}
                                            </span>
                                        </span>
                                        <span className="notify-item__preview">
                                            {c.has_question && <span className="question-chip">Вопрос</span>}
                                            {c.last_message.preview}
                                        </span>
                                        <time className="notify-item__time" dateTime={c.last_message.created_at}>
                                            {formatMessageTime(c.last_message.created_at)}
                                        </time>
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    );
}

export default NotificationsBell;
