import { useEffect, useRef, useState } from 'react';
import api from '../api';
import { CloseIcon } from './ChatPanel';
import { messageLength } from '../lib/chatSocket';
import { useKeyboardInset } from '../lib/keyboardInset';
import { formatMessageTime } from '../lib/notifications';
import './Discussion.css';
import './Notifications.css'; // .unread-badge

// Longest post, in characters (code points): api/discussions.py MAX_COMMENT_LENGTH.
const MAX_COMMENT_LENGTH = 2000;

/**
 * «💬 N» in a task block's head: N = threads this user may read; opens and
 * closes the block's discussion. For the course author, a red count of open
 * reports on it. discussion: { count, reports, open, onToggle, panelId }
 * (LessonViewer), or nothing (no discussions: embeds, logged out).
 */
export function DiscussionBadge({ blockId, discussion }) {
    if (!discussion) return null;
    const { count, reports = 0, open, onToggle, panelId } = discussion;
    const label = `Обсуждение задания: ${count}` + (reports > 0 ? `, жалоб: ${reports}` : '');
    return (
        <button
            type="button"
            id={`discuss-${blockId}`}
            className={open ? 'lesson-block__discuss lesson-block__discuss--open' : 'lesson-block__discuss'}
            onClick={onToggle}
            aria-expanded={open}
            aria-controls={open ? panelId : undefined}
            aria-label={label}
            title={label}
        >
            <span aria-hidden="true">💬</span> {count}
            {reports > 0 && <span className="unread-badge" aria-hidden="true">{reports > 9 ? '9+' : reports}</span>}
        </button>
    );
}

function errorText(err, fallback) {
    return err.response?.data?.detail || fallback;
}

/**
 * A text box with a send button: a new thread or a reply. onSend(text) posts
 * it and may throw (the server's message is shown, e.g. the once-a-minute
 * limit); the text stays until it has been sent.
 */
function PostForm({ id, label, hideLabel, placeholder, submitLabel, onSend, onCancel, autoFocus }) {
    const [text, setText] = useState('');
    const [sending, setSending] = useState(false);
    const [error, setError] = useState('');
    const ref = useRef(null);
    const length = messageLength(text.trim());
    const tooLong = length > MAX_COMMENT_LENGTH;
    const canSend = length > 0 && !tooLong && !sending;

    useEffect(() => {
        if (autoFocus) ref.current?.focus();
    }, [autoFocus]);

    async function handleSubmit(e) {
        e.preventDefault();
        if (!canSend) return;
        setSending(true);
        setError('');
        try {
            await onSend(text.trim());
            setText('');
        } catch (err) {
            setError(errorText(err, 'Не отправлено. Попробуйте ещё раз.'));
        } finally {
            setSending(false);
        }
    }

    return (
        <form className="discussion-form" onSubmit={handleSubmit}>
            <label className={hideLabel ? 'visually-hidden' : 'discussion-form__label'} htmlFor={id}>{label}</label>
            <textarea
                ref={ref}
                id={id}
                className="input discussion-form__text"
                rows={3}
                value={text}
                onChange={e => { setText(e.target.value); setError(''); }}
                placeholder={placeholder}
                aria-invalid={tooLong || undefined}
            />
            {tooLong && (
                <p className="discussion-form__error" role="alert">
                    Слишком длинно: не больше {MAX_COMMENT_LENGTH} символов ({length}).
                </p>
            )}
            {error && <p className="discussion-form__error" role="alert">{error}</p>}
            <div className="discussion-form__actions">
                {onCancel && <button type="button" className="btn btn-secondary btn-sm" onClick={onCancel}>Отмена</button>}
                <button type="submit" className="btn btn-primary btn-sm" disabled={!canSend}>
                    {sending ? 'Отправляем…' : submitLabel}
                </button>
            </div>
        </form>
    );
}

/**
 * One post. User text is always a text node, never HTML. Moderation, as the
 * server allows (can_* flags): students report; the course author sees open
 * reports, dismisses them, deletes, bans and unbans the writer.
 */
function CommentItem({ comment, actions }) {
    const reports = comment.report_count || 0;
    return (
        <li className={reports > 0 ? 'discussion-comment discussion-comment--reported' : 'discussion-comment'}>
            <p className="discussion-comment__meta">
                <span className="discussion-comment__author">{comment.user_name}</span>
                {comment.is_course_author && <span className="discussion-chip">Автор курса</span>}
                {comment.user_is_banned && <span className="discussion-chip discussion-chip--muted">Заблокирован</span>}
                <time className="discussion-comment__time" dateTime={comment.created_at}>
                    {formatMessageTime(comment.created_at)}
                </time>
            </p>
            {comment.is_deleted ? (
                <>
                    <p className="discussion-comment__deleted">Комментарий удалён</p>
                    {/* Only the course author still gets the text (moderation). */}
                    {comment.text !== null && <p className="discussion-comment__text discussion-comment__text--deleted">{comment.text}</p>}
                </>
            ) : (
                <p className="discussion-comment__text">{comment.text}</p>
            )}
            {reports > 0 && (
                <p className="discussion-comment__reports">
                    <span className="discussion-chip discussion-chip--danger">Жалоб: {reports}</span>
                    <button type="button" className="discussion-link" onClick={() => actions.dismiss(comment)}>
                        Отклонить жалобы
                    </button>
                </p>
            )}
            {(comment.can_delete || comment.can_ban || comment.can_report || comment.reported) && (
                <p className="discussion-comment__actions">
                    {comment.can_delete && (
                        <button type="button" className="discussion-link discussion-link--danger" onClick={() => actions.remove(comment)}>
                            Удалить
                        </button>
                    )}
                    {comment.can_ban && (
                        <button type="button" className="discussion-link" onClick={() => actions.ban(comment)}>
                            {comment.user_is_banned ? 'Разблокировать' : 'Заблокировать'}
                        </button>
                    )}
                    {comment.can_report && (
                        <button type="button" className="discussion-link discussion-link--quiet" onClick={() => actions.report(comment)}>
                            Пожаловаться
                        </button>
                    )}
                    {comment.reported && <span className="discussion-comment__note">Жалоба отправлена</span>}
                </p>
            )}
        </li>
    );
}

function ThreadItem({ thread, canPost, onChange, onRemove, onModerated, onBan }) {
    // Resolved threads start collapsed (one line); the rest are open.
    const [expanded, setExpanded] = useState(!thread.is_resolved);
    const [replying, setReplying] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const first = thread.comments[0];
    const bodyId = `discussion-thread-${thread.id}`;

    async function patch(data) {
        setBusy(true);
        setError('');
        try {
            const res = await api.patch(`/threads/${thread.id}/`, data);
            onChange(res.data);
            if ('is_resolved' in data) setExpanded(!data.is_resolved);
        } catch (err) {
            setError(errorText(err, 'Не получилось. Попробуйте ещё раз.'));
        } finally {
            setBusy(false);
        }
    }

    async function removeThread() {
        if (!window.confirm('Удалить обсуждение со всеми ответами?')) return;
        setBusy(true);
        try {
            await api.delete(`/threads/${thread.id}/`);
            onRemove(thread);
        } catch (err) {
            setError(errorText(err, 'Не удалось удалить. Попробуйте ещё раз.'));
            setBusy(false);
        }
    }

    // A request that answers with the comment, which then replaces it here.
    async function commentAction(comment, confirmText, request, fallback) {
        if (confirmText && !window.confirm(confirmText)) return;
        setError('');
        try {
            const res = await request();
            onChange({ ...thread, comments: thread.comments.map(c => (c.id === comment.id ? res.data : c)) });
            onModerated();
        } catch (err) {
            setError(errorText(err, fallback));
        }
    }

    const commentActions = {
        remove: comment => commentAction(comment, 'Удалить комментарий?',
            () => api.delete(`/comments/${comment.id}/`), 'Не удалось удалить. Попробуйте ещё раз.'),
        report: comment => commentAction(comment, 'Пожаловаться на комментарий? Его увидит автор курса.',
            () => api.post(`/comments/${comment.id}/report/`), 'Жалоба не отправлена. Попробуйте ещё раз.'),
        dismiss: comment => commentAction(comment, null,
            () => api.post(`/comments/${comment.id}/dismiss-reports/`), 'Не получилось. Попробуйте ещё раз.'),
        ban: async comment => {
            setError('');
            try {
                await onBan(comment);
            } catch (err) {
                setError(errorText(err, 'Не получилось. Попробуйте ещё раз.'));
            }
        },
    };

    async function sendReply(text) {
        const res = await api.post(`/threads/${thread.id}/comments/`, { text });
        onChange({ ...thread, comments: [...thread.comments, res.data] });
        setReplying(false);
    }

    const className = ['discussion-thread',
        thread.is_pinned && 'discussion-thread--pinned',
        thread.is_resolved && 'discussion-thread--resolved'].filter(Boolean).join(' ');
    const replies = thread.comments.length - 1;

    return (
        <li className={className}>
            {(thread.is_pinned || thread.is_resolved) && (
                <p className="discussion-thread__chips">
                    {thread.is_pinned && <span className="discussion-chip">Закреплено</span>}
                    {thread.is_resolved && <span className="discussion-chip discussion-chip--resolved">✓ Решено</span>}
                </p>
            )}

            {!expanded ? (
                <button type="button" className="discussion-thread__summary" onClick={() => setExpanded(true)}
                    aria-expanded="false" aria-controls={bodyId}>
                    <span className="discussion-thread__summary-text">
                        {first.is_deleted ? 'Комментарий удалён' : first.text}
                    </span>
                    <span className="discussion-thread__summary-more">
                        {first.user_name}{replies > 0 ? ` · ответов: ${replies}` : ''} · показать
                    </span>
                </button>
            ) : (
                <div id={bodyId}>
                    <ol className="discussion-comments">
                        {thread.comments.map(c => <CommentItem key={c.id} comment={c} actions={commentActions} />)}
                    </ol>

                    {error && <p className="discussion-form__error" role="alert">{error}</p>}

                    {replying ? (
                        <PostForm
                            id={`discussion-reply-${thread.id}`}
                            label="Ваш ответ"
                            hideLabel
                            placeholder="Ваш ответ"
                            submitLabel="Ответить"
                            onSend={sendReply}
                            onCancel={() => setReplying(false)}
                            autoFocus
                        />
                    ) : (
                        <div className="discussion-thread__actions">
                            {canPost && (
                                <button type="button" className="discussion-link" onClick={() => setReplying(true)}>Ответить</button>
                            )}
                            {thread.can_resolve && (
                                <button type="button" className="discussion-link" disabled={busy}
                                    onClick={() => patch({ is_resolved: !thread.is_resolved })}>
                                    {thread.is_resolved ? 'Открыть снова' : 'Отметить решённым'}
                                </button>
                            )}
                            {thread.can_pin && (
                                <button type="button" className="discussion-link" disabled={busy}
                                    onClick={() => patch({ is_pinned: !thread.is_pinned })}>
                                    {thread.is_pinned ? 'Открепить' : 'Закрепить'}
                                </button>
                            )}
                            {thread.can_delete && (
                                <button type="button" className="discussion-link discussion-link--danger" disabled={busy}
                                    onClick={removeThread}>
                                    Удалить обсуждение
                                </button>
                            )}
                            {thread.is_resolved && (
                                <button type="button" className="discussion-link" onClick={() => setExpanded(false)}
                                    aria-expanded="true" aria-controls={bodyId}>
                                    Свернуть
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}
        </li>
    );
}

// Server order: pinned first, then open, then resolved; newest first.
function sortThreads(threads) {
    return [...threads].sort((a, b) => (b.is_pinned - a.is_pinned)
        || (a.is_resolved - b.is_resolved)
        || (new Date(b.created_at) - new Date(a.created_at))
        || (b.id - a.id));
}

/**
 * The discussion of one task block: public threads, next to the private chat
 * with the teacher. GET /api/blocks/<id>/threads/ (again when `solved`
 * changes: solving shows every thread); the server decides what this user may
 * read and do (can_* flags). A right-hand panel; a bottom sheet on phones
 * (Discussion.css). Not modal: Esc and the close button call onClose, which
 * returns focus. onThreadsChanged: a thread was started or deleted, or
 * reports changed (the block's «💬 N» and, for the course author, its open
 * reports).
 */
function DiscussionPanel({ id, blockId, title, solved, onClose, onThreadsChanged }) {
    const [data, setData] = useState(null);
    const [loadError, setLoadError] = useState(false);
    const [attempt, setAttempt] = useState(0);
    const panelRef = useRef(null);
    const titleId = `${id}-title`;

    useKeyboardInset(panelRef, true, 'discussion-panel--keyboard');

    useEffect(() => {
        let cancelled = false;
        api.get(`/blocks/${blockId}/threads/`)
            .then(res => {
                if (cancelled) return;
                setData(res.data);
                setLoadError(false);
            })
            .catch(err => {
                console.error('Failed to load the discussion:', err);
                if (!cancelled) setLoadError(true);
            });
        return () => { cancelled = true; };
    }, [blockId, solved, attempt]);

    // Below the sticky app header, whatever its height.
    useEffect(() => {
        const header = document.querySelector('.app-header');
        const panel = panelRef.current;
        if (!header || !panel) return undefined;
        function update() {
            panel.style.setProperty('--discussion-top', `${Math.max(0, Math.round(header.getBoundingClientRect().bottom))}px`);
        }
        update();
        const observer = new ResizeObserver(update);
        observer.observe(header);
        return () => observer.disconnect();
    }, []);

    // Focus into the panel (not into a text box: on phones that would raise the keyboard).
    useEffect(() => {
        panelRef.current?.focus();
    }, []);

    function handleKeyDown(e) {
        if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
        }
    }

    function replaceThread(thread) {
        setData(current => ({ ...current, threads: sortThreads(current.threads.map(t => (t.id === thread.id ? thread : t))) }));
    }

    function removeThread(thread) {
        setData(current => ({ ...current, threads: current.threads.filter(t => t.id !== thread.id) }));
        onThreadsChanged();
    }

    // Ban / unban a comment's writer (all the author's courses): every post
    // of theirs here shows it.
    async function toggleBan(comment) {
        const banned = comment.user_is_banned;
        const question = banned
            ? `Разблокировать ${comment.user_name}? Снова сможет писать в обсуждения.`
            : `Заблокировать ${comment.user_name}? Не сможет писать в обсуждения ваших курсов, но сможет их читать.`;
        if (!window.confirm(question)) return;
        if (banned) await api.delete(`/discussions/bans/${comment.user}/`);
        else await api.post('/discussions/bans/', { user_id: comment.user });
        setData(current => ({
            ...current,
            threads: current.threads.map(t => ({
                ...t,
                comments: t.comments.map(c => (c.user === comment.user ? { ...c, user_is_banned: !banned } : c)),
            })),
        }));
    }

    async function startThread(text) {
        const res = await api.post(`/blocks/${blockId}/threads/`, { text });
        setData(current => ({ ...current, threads: sortThreads([res.data, ...current.threads]) }));
        onThreadsChanged();
    }

    return (
        <aside
            ref={panelRef}
            id={id}
            className="discussion-panel"
            aria-labelledby={titleId}
            tabIndex={-1}
            onKeyDown={handleKeyDown}
        >
            <div className="discussion-panel__header">
                <div className="discussion-panel__heading">
                    <h2 id={titleId} className="discussion-panel__title">Обсуждение</h2>
                    <p className="discussion-panel__subtitle">{title} · видят все учащиеся курса</p>
                </div>
                <button type="button" className="chat-panel__close" onClick={onClose}
                    aria-label="Закрыть обсуждение" title="Закрыть (Esc)">
                    <CloseIcon />
                </button>
            </div>

            <div className="discussion-panel__body">
                {loadError && (
                    <div className="notice notice-danger" role="alert">
                        Не удалось загрузить обсуждение.{' '}
                        <button type="button" className="discussion-link" onClick={() => setAttempt(n => n + 1)}>Повторить</button>
                    </div>
                )}
                {!data && !loadError && <p className="discussion-panel__note" role="status">Загружаем…</p>}

                {data && (
                    <>
                        {data.can_post ? (
                            <PostForm
                                id={`${id}-new`}
                                label="Новое обсуждение"
                                placeholder="Вопрос или подсказка для других. Готовое решение не публикуйте."
                                submitLabel="Опубликовать"
                                onSend={startThread}
                            />
                        ) : (
                            <p className="notice notice-warning">
                                Автор курса закрыл вам возможность писать в обсуждения. Читать их можно.
                            </p>
                        )}

                        {data.hidden_count > 0 && (
                            <p className="discussion-panel__note">
                                Ещё обсуждений: {data.hidden_count}. Они откроются, когда вы решите задачу.
                            </p>
                        )}

                        {data.threads.length === 0 ? (
                            <p className="discussion-panel__note">Пока никто ничего не написал.</p>
                        ) : (
                            <ol className="discussion-list">
                                {data.threads.map(t => (
                                    <ThreadItem key={t.id} thread={t} canPost={data.can_post} onChange={replaceThread}
                                        onRemove={removeThread} onModerated={onThreadsChanged} onBan={toggleBan} />
                                ))}
                            </ol>
                        )}
                    </>
                )}
            </div>
        </aside>
    );
}

export default DiscussionPanel;
