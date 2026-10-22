import { useEffect, useRef } from 'react';
import { MAX_MESSAGE_LENGTH, messageLength } from '../lib/chatSocket';
import { useKeyboardInset } from '../lib/keyboardInset';
import QuestionCard from './QuestionCard';
import './ChatPanel.css';

// Presentational chat window shared by the lesson page (floating, student →
// teacher) and the course page (inline, teacher → one student). The pages own
// the WebSocket, history fetch and sending; this component only renders them.

const timeFormat = new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' });
const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
});

// "14:05" for today, "12 окт., 14:05" for older messages.
function formatTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    const today = new Date().toDateString() === date.toDateString();
    return (today ? timeFormat : dateTimeFormat).format(date);
}

export function ChatIcon() {
    return (
        <svg className="chat-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z" />
        </svg>
    );
}

export function CloseIcon() {
    return (
        <svg className="chat-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M6 6l12 12M18 6L6 18" />
        </svg>
    );
}

function SendIcon() {
    return (
        <svg className="chat-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M5 12h13M12 5l7 7-7 7" />
        </svg>
    );
}

function ChatPanel({
    id,
    variant = 'floating',
    title,
    subtitle,
    messages,
    isOwn,
    emptyHint,
    status,
    historyError,
    sendError,
    value,
    onChange,
    onSubmit,
    sending,
    onClose,
    headingLevel = 2,
}) {
    const panelRef = useRef(null);
    const logRef = useRef(null);
    const floating = variant === 'floating';
    const titleId = `${id}-title`;
    const inputId = `${id}-input`;
    const connected = status === 'open';
    const counterId = `${id}-counter`;
    const length = messageLength(value.trim());
    const tooLong = length > MAX_MESSAGE_LENGTH;
    // The counter appears near the limit.
    const showCounter = length >= MAX_MESSAGE_LENGTH * 0.9;
    const Heading = `h${headingLevel}`;

    useKeyboardInset(panelRef, floating, 'chat-panel--keyboard');

    // Move focus into the window when it opens (not into the input: on phones
    // that would raise the keyboard over the history straight away).
    useEffect(() => {
        panelRef.current?.focus();
    }, []);

    // Newest message in view: on open, whenever one arrives, and when a status
    // note above the input appears or goes (it changes the list's height).
    useEffect(() => {
        const log = logRef.current;
        if (log) log.scrollTop = log.scrollHeight;
    }, [messages.length, status, historyError, tooLong, sendError]);

    function handleKeyDown(e) {
        if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
        }
    }

    // Notes above the input, in a live region. 'reconnecting' is neutral (it
    // fixes itself); red only for what the user has to act on.
    const notes = [];
    if (status === 'connecting') {
        notes.push({ key: 'status', text: 'Подключение…' });
    } else if (status === 'reconnecting') {
        notes.push({ key: 'status', text: 'Связь прервалась. Переподключаемся…' });
    } else if (status === 'forbidden') {
        notes.push({ key: 'status', error: true, text: 'Нет доступа к этому чату.' });
    } else if (status === 'session') {
        notes.push({ key: 'status', error: true, text: 'Сессия истекла. Войдите снова, чтобы писать в чат.' });
    }
    // Static text, so the live region does not speak on every keystroke;
    // the number is in the counter.
    if (tooLong) {
        notes.push({ key: 'length', error: true, text: `Сообщение слишком длинное: не больше ${MAX_MESSAGE_LENGTH} символов.` });
    } else if (sendError) {
        notes.push({ key: 'send', error: true, text: sendError });
    }

    return (
        <section
            ref={panelRef}
            id={id}
            className={`chat-panel chat-panel--${variant}`}
            role={floating ? 'dialog' : 'region'}
            aria-labelledby={titleId}
            tabIndex={-1}
            onKeyDown={handleKeyDown}
        >
            <header className="chat-panel__header">
                <div className="chat-panel__heading">
                    <Heading className="chat-panel__title" id={titleId}>{title}</Heading>
                    {subtitle && <p className="chat-panel__subtitle">{subtitle}</p>}
                </div>
                <button
                    type="button"
                    className="chat-panel__close"
                    onClick={onClose}
                    aria-label="Закрыть чат"
                    title="Закрыть чат (Esc)"
                >
                    <CloseIcon />
                </button>
            </header>

            <div
                ref={logRef}
                className="chat-panel__log"
                role="log"
                aria-live="polite"
                aria-label="Сообщения"
                // Scrollable region: focusable so keyboard users can scroll it.
                tabIndex={0}
            >
                {historyError && (
                    <p className="chat-panel__note chat-panel__note--error">
                        Не удалось загрузить историю сообщений.
                    </p>
                )}
                {messages.length === 0 ? (
                    !historyError && (
                        <div className="chat-panel__empty">
                            <p className="chat-panel__empty-title">Сообщений пока нет</p>
                            {emptyHint && <p className="chat-panel__empty-hint">{emptyHint}</p>}
                        </div>
                    )
                ) : (
                    <ol className="chat-panel__messages">
                        {messages.map(msg => {
                            const own = isOwn(msg);
                            const time = formatTime(msg.created_at);
                            return (
                                <li
                                    key={msg.id}
                                    className={own ? 'chat-message chat-message--own' : 'chat-message'}
                                >
                                    <p className="chat-message__meta">
                                        {own
                                            ? <span className="visually-hidden">Вы</span>
                                            : <span className="chat-message__author">{msg.sender_username}</span>}
                                        {time && (
                                            <time className="chat-message__time" dateTime={msg.created_at}>
                                                {time}
                                            </time>
                                        )}
                                    </p>
                                    {msg.context
                                        ? <QuestionCard message={msg} own={own} />
                                        : <p className="chat-message__text">{msg.text}</p>}
                                </li>
                            );
                        })}
                    </ol>
                )}
            </div>

            <div className="chat-panel__status" role="status">
                {notes.map(note => (
                    <p key={note.key} className={note.error ? 'chat-panel__note chat-panel__note--error' : 'chat-panel__note'}>
                        {note.text}
                    </p>
                ))}
            </div>

            <form className="chat-panel__form" onSubmit={onSubmit}>
                <label className="visually-hidden" htmlFor={inputId}>Сообщение</label>
                <input
                    id={inputId}
                    className="input chat-panel__input"
                    type="text"
                    placeholder="Написать сообщение..."
                    autoComplete="off"
                    value={value}
                    onChange={onChange}
                    aria-invalid={tooLong || undefined}
                    aria-describedby={showCounter ? counterId : undefined}
                />
                {showCounter && (
                    <span
                        id={counterId}
                        className={tooLong ? 'chat-panel__counter chat-panel__counter--over' : 'chat-panel__counter'}
                    >
                        {length} / {MAX_MESSAGE_LENGTH}
                    </span>
                )}
                <button
                    type="submit"
                    className="btn btn-primary chat-panel__send"
                    disabled={sending || !connected || tooLong}
                    aria-label="Отправить"
                    title="Отправить"
                >
                    <SendIcon />
                </button>
            </form>
        </section>
    );
}

export default ChatPanel;
