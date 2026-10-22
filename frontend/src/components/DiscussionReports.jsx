import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { formatMessageTime } from '../lib/notifications';
import './Discussion.css';

function errorText(err, fallback) {
    return err.response?.data?.detail || fallback;
}

/**
 * «Жалобы в обсуждениях» on the course author's dashboard: comments students
 * reported in her courses (GET /api/discussions/reports/, latest first), with
 * what to do about each (open the task's discussion, delete, dismiss, ban the
 * writer), and the users she has banned (GET /api/discussions/bans/).
 * Comment text is plain text, rendered as a text node.
 */
function DiscussionReports() {
    const [reports, setReports] = useState(null);
    const [bans, setBans] = useState([]);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        try {
            const [reportsRes, bansRes] = await Promise.all([
                api.get('/discussions/reports/'),
                api.get('/discussions/bans/'),
            ]);
            setReports(reportsRes.data.reports);
            setBans(bansRes.data.bans);
        } catch (err) {
            console.error('Failed to load discussion reports:', err);
            setError('Не удалось загрузить жалобы.');
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    async function act(confirmText, request) {
        if (confirmText && !window.confirm(confirmText)) return;
        setBusy(true);
        setError('');
        try {
            await request();
            await load();
        } catch (err) {
            setError(errorText(err, 'Не получилось. Попробуйте ещё раз.'));
        } finally {
            setBusy(false);
        }
    }

    const removeComment = r => act('Удалить комментарий?', () => api.delete(`/comments/${r.comment.id}/`));
    const dismiss = r => act(null, () => api.post(`/comments/${r.comment.id}/dismiss-reports/`));
    const ban = r => act(
        `Заблокировать ${r.comment.user_name}? Не сможет писать в обсуждения ваших курсов, но сможет их читать.`,
        () => api.post('/discussions/bans/', { user_id: r.comment.user }));
    const unban = b => act(`Разблокировать ${b.user_name}?`, () => api.delete(`/discussions/bans/${b.user_id}/`));

    return (
        <section className="section">
            <div className="section__header">
                <h2 className="section__title">Жалобы в обсуждениях</h2>
            </div>
            {error && <p className="notice notice-danger" role="alert">{error}</p>}
            {reports === null && !error && <p className="muted" role="status">Загружаем…</p>}
            {reports && reports.length === 0 && <p className="muted">Жалоб нет.</p>}
            {reports && reports.length > 0 && (
                <ul className="inbox-list">
                    {reports.map(r => (
                        <li key={r.comment.id} className="report-item">
                            <p className="report-item__where">{r.course_title} › {r.lesson_title}</p>
                            <p className="discussion-comment__meta">
                                <span className="discussion-comment__author">{r.comment.user_name}</span>
                                {r.comment.user_is_banned && <span className="discussion-chip discussion-chip--muted">Заблокирован</span>}
                                <time className="discussion-comment__time" dateTime={r.comment.created_at}>
                                    {formatMessageTime(r.comment.created_at)}
                                </time>
                                <span className="discussion-chip discussion-chip--danger">Жалоб: {r.report_count}</span>
                            </p>
                            <p className="discussion-comment__text report-item__text">{r.comment.text}</p>
                            <p className="discussion-comment__actions">
                                <Link className="discussion-link" to={`/lesson/${r.lesson_id}/?discussion=${r.block_id}#block-${r.block_id}`}>
                                    Открыть обсуждение
                                </Link>
                                <button type="button" className="discussion-link discussion-link--danger" disabled={busy}
                                    onClick={() => removeComment(r)}>
                                    Удалить
                                </button>
                                <button type="button" className="discussion-link" disabled={busy} onClick={() => dismiss(r)}>
                                    Отклонить жалобы
                                </button>
                                {!r.comment.user_is_banned && r.comment.can_ban && (
                                    <button type="button" className="discussion-link" disabled={busy} onClick={() => ban(r)}>
                                        Заблокировать
                                    </button>
                                )}
                            </p>
                        </li>
                    ))}
                </ul>
            )}

            {bans.length > 0 && (
                <>
                    <h3 className="report-bans__title">Заблокированы в обсуждениях</h3>
                    <ul className="report-bans">
                        {bans.map(b => (
                            <li key={b.user_id} className="report-bans__item">
                                <span>{b.user_name}{b.user_name !== b.username ? ` (${b.username})` : ''}</span>
                                <button type="button" className="discussion-link" disabled={busy} onClick={() => unban(b)}>
                                    Разблокировать
                                </button>
                            </li>
                        ))}
                    </ul>
                </>
            )}
        </section>
    );
}

export default DiscussionReports;
