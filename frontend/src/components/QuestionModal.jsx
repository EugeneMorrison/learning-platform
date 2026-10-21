import { useEffect, useRef, useState } from 'react';
import api from '../api';
import { MAX_MESSAGE_LENGTH, messageLength } from '../lib/chatSocket';
import { CloseIcon } from './ChatPanel';
import QuestionContext from './QuestionContext';
import './Question.css';

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, summary, [tabindex]:not([tabindex="-1"])';

/**
 * «Задать вопрос» (a student, about one task): a modal dialog with a read-only
 * preview of what will be attached, from the server itself
 * (POST /api/questions/preview/, the same snapshot POST /api/questions/
 * saves), and the question. «Отправить» stays disabled until the text has
 * something in it. onSent(message) gets the saved chat message.
 *
 * draft: CODE only, the editor's current code (the server drops it when it
 * equals the latest submission or the starter code).
 */
function QuestionModal({ blockId, draft, onClose, onSent }) {
    const [context, setContext] = useState(null);
    const [previewError, setPreviewError] = useState('');
    const [text, setText] = useState('');
    const [sending, setSending] = useState(false);
    const [sendError, setSendError] = useState('');
    const dialogRef = useRef(null);
    const textareaRef = useRef(null);

    const body = draft === undefined ? { block_id: blockId } : { block_id: blockId, draft };
    const length = messageLength(text.trim());
    const tooLong = length > MAX_MESSAGE_LENGTH;
    const canSend = length > 0 && !tooLong && !sending;

    useEffect(() => {
        let cancelled = false;
        api.post('/questions/preview/', body)
            .then(res => { if (!cancelled) setContext(res.data); })
            .catch(err => {
                if (!cancelled) setPreviewError(err.response?.data?.detail || 'Не удалось подготовить вложение.');
            });
        return () => { cancelled = true; };
        // The preview is built once, for the draft as it was when the dialog opened.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Focus the question; lock the page behind; give focus back on close.
    useEffect(() => {
        const opener = document.activeElement;
        textareaRef.current?.focus();
        document.documentElement.classList.add('question-modal-open');
        return () => {
            document.documentElement.classList.remove('question-modal-open');
            if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
        };
    }, []);

    function handleKeyDown(e) {
        if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
            return;
        }
        if (e.key !== 'Tab') return;
        // Keep Tab inside the dialog.
        const items = [...dialogRef.current.querySelectorAll(FOCUSABLE)];
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

    async function handleSubmit(e) {
        e.preventDefault();
        if (!canSend) return;
        setSending(true);
        setSendError('');
        try {
            const res = await api.post('/questions/', { ...body, text: text.trim() });
            onSent(res.data);
        } catch (err) {
            setSendError(err.response?.data?.detail || 'Вопрос не отправлен. Попробуйте ещё раз.');
            setSending(false);
        }
    }

    return (
        <div className="question-modal-layer" onKeyDown={handleKeyDown}>
            <div className="question-modal__backdrop" onClick={onClose} aria-hidden="true" />
            <div
                ref={dialogRef}
                className="question-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="question-modal-title"
            >
                <div className="question-modal__head">
                    <div>
                        <h2 id="question-modal-title" className="question-modal__title">Вопрос учителю</h2>
                        {context && (
                            <p className="question-modal__where">{context.course.title} › {context.lesson.title}</p>
                        )}
                    </div>
                    <button type="button" className="btn btn-ghost btn-sm question-modal__close" onClick={onClose}
                        aria-label="Закрыть" title="Закрыть (Esc)">
                        <CloseIcon />
                    </button>
                </div>

                <div className="question-modal__scroll">
                    <p className="question-modal__hint">К вопросу приложится:</p>
                    {!context && !previewError && <p className="question-modal__hint" role="status">Готовим вложение…</p>}
                    {previewError && <p className="notice notice-danger" role="alert">{previewError}</p>}
                    {context && <QuestionContext context={context} />}
                </div>

                <form className="question-modal__form" onSubmit={handleSubmit}>
                    <label className="question-modal__label" htmlFor="question-modal-text">Ваш вопрос</label>
                    <textarea
                        ref={textareaRef}
                        id="question-modal-text"
                        className="input question-modal__text"
                        rows={4}
                        value={text}
                        onChange={e => { setText(e.target.value); setSendError(''); }}
                        placeholder="Что непонятно или не получается?"
                        aria-invalid={tooLong || undefined}
                    />
                    {tooLong && (
                        <p className="question-modal__error" role="alert">
                            Слишком длинно: не больше {MAX_MESSAGE_LENGTH} символов ({length}).
                        </p>
                    )}
                    {sendError && <p className="question-modal__error" role="alert">{sendError}</p>}
                    <div className="question-modal__actions">
                        <button type="button" className="btn btn-secondary" onClick={onClose}>Отмена</button>
                        <button type="submit" className="btn btn-primary" disabled={!canSend}>
                            {sending ? 'Отправляем…' : 'Отправить'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

export default QuestionModal;
