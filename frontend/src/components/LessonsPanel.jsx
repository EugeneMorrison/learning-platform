import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import './LessonsPanel.css';

export function ListIcon() {
    return (
        <svg className="lessons-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />
        </svg>
    );
}

function CloseIcon() {
    return (
        <svg className="lessons-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M6 6l12 12M18 6L6 18" />
        </svg>
    );
}

const FOCUSABLE = 'a[href], button:not([disabled])';

/**
 * "Список уроков": every lesson of the course, sliding in from the left.
 * Data: GET /api/lessons/outline/?course=<id>, fetched on each open so the
 * counts agree with the header's "Решено X из Y задач" (same rule on the
 * server: QUIZ/CODE/FILL tasks, solved = correct). The course author gets
 * solved_count null and sees no counts. Modal dialog: focus moves in, Tab
 * stays inside, Esc / backdrop / close button / choosing a lesson close it,
 * and the page behind doesn't scroll. The caller returns focus on close.
 */
function LessonsPanel({ courseId, courseTitle, currentLessonId, onClose }) {
    const [lessons, setLessons] = useState(null);
    const [error, setError] = useState(false);
    const [attempt, setAttempt] = useState(0);
    const panelRef = useRef(null);
    const closeRef = useRef(null);

    // Fetched on every open (and on "Повторить"); starts as "loading".
    useEffect(() => {
        let cancelled = false;
        api.get('/lessons/outline/', { params: { course: courseId } })
            .then(res => { if (!cancelled) setLessons(res.data); })
            .catch(err => {
                console.error('Failed to load lessons:', err);
                if (!cancelled) setError(true);
            });
        return () => { cancelled = true; };
    }, [courseId, attempt]);

    function retry() {
        setError(false);
        setLessons(null);
        setAttempt(n => n + 1);
    }

    // Focus into the panel; lock the page behind while open.
    useEffect(() => {
        closeRef.current?.focus();
        document.documentElement.classList.add('lessons-panel-open');
        return () => document.documentElement.classList.remove('lessons-panel-open');
    }, []);

    function handleKeyDown(e) {
        if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
            return;
        }
        if (e.key !== 'Tab') return;
        // Keep Tab inside the dialog.
        const items = [...panelRef.current.querySelectorAll(FOCUSABLE)];
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    return (
        <div className="lessons-panel-layer" onKeyDown={handleKeyDown}>
            <div className="lessons-panel__backdrop" onClick={onClose} aria-hidden="true" />
            <div
                ref={panelRef}
                className="lessons-panel"
                role="dialog"
                aria-modal="true"
                aria-labelledby="lessons-panel-title"
            >
                <div className="lessons-panel__head">
                    <div className="lessons-panel__heading">
                        <h2 id="lessons-panel-title" className="lessons-panel__title">Уроки курса</h2>
                        {courseTitle && <p className="lessons-panel__course">{courseTitle}</p>}
                    </div>
                    <button
                        ref={closeRef}
                        type="button"
                        className="btn btn-ghost btn-sm lessons-panel__close"
                        onClick={onClose}
                        aria-label="Закрыть список уроков"
                        title="Закрыть"
                    >
                        <CloseIcon />
                    </button>
                </div>

                {!lessons && !error && (
                    <p className="lessons-panel__status" role="status">Загрузка уроков…</p>
                )}

                {error && (
                    <div className="lessons-panel__status" role="alert">
                        <p className="notice notice-danger">
                            Не удалось загрузить список уроков. Проверьте соединение и попробуйте ещё раз.
                        </p>
                        <button type="button" className="btn btn-secondary btn-sm" onClick={retry}>
                            Повторить
                        </button>
                    </div>
                )}

                {lessons && (
                    <ol className="lessons-panel__list">
                        {lessons.map(lesson => {
                            const current = String(lesson.id) === String(currentLessonId);
                            const showCount = lesson.solved_count !== null && lesson.task_count > 0;
                            const solved = showCount && lesson.solved_count === lesson.task_count;
                            return (
                                <li key={lesson.id}>
                                    <Link
                                        to={`/lesson/${lesson.id}/`}
                                        className={current
                                            ? 'lessons-panel__link lessons-panel__link--current'
                                            : 'lessons-panel__link'}
                                        aria-current={current ? 'page' : undefined}
                                        onClick={() => {
                                            onClose();
                                            if (!current) window.scrollTo(0, 0);
                                        }}
                                    >
                                        <span className="lessons-panel__num">{lesson.position}</span>
                                        <span className="lessons-panel__name">{lesson.title}</span>
                                        {showCount && (
                                            <span className={solved
                                                ? 'lessons-panel__count lessons-panel__count--solved'
                                                : 'lessons-panel__count'}
                                            >
                                                {solved && <span aria-hidden="true">✓ </span>}
                                                {lesson.solved_count} из {lesson.task_count}
                                                {solved && <span className="visually-hidden">, урок пройден</span>}
                                            </span>
                                        )}
                                    </Link>
                                </li>
                            );
                        })}
                    </ol>
                )}
            </div>
        </div>
    );
}

export default LessonsPanel;
