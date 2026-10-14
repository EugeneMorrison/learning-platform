import { useState, useRef, useEffect } from 'react';
import './EditableTitle.css';

const MAX_TITLE_LENGTH = 255; // Course.title / Lesson.title

// Server message for a rejected title ({"title": ["..."]}), else a generic one.
function saveErrorMessage(err) {
    const data = err.response?.data;
    return data?.title?.[0] || data?.detail || 'Не удалось сохранить название. Попробуйте ещё раз.';
}

/**
 * A title that its owner can rename in place: pencil → input prefilled with the
 * current title. Enter saves, Esc or clicking away cancels (nothing is saved
 * by accident). Without `canEdit` it is just the plain element.
 *
 * onSave(title) is async and throws when the request fails; the component shows
 * the error and stays in edit mode. The caller updates its own state on success.
 * `display` renders the read-only content when it is more than the bare title
 * (e.g. a link with a "Урок 2:" prefix).
 */
function EditableTitle({ value, canEdit, onSave, as = 'span', className, display }) {
    const Tag = as;
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(value);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const inputRef = useRef(null);
    const pencilRef = useRef(null);
    const returnFocus = useRef(false);

    useEffect(() => {
        if (editing) {
            inputRef.current?.focus();
            inputRef.current?.select();
        } else if (returnFocus.current) {
            returnFocus.current = false;
            pencilRef.current?.focus();
        }
    }, [editing]);

    const content = display ?? value;
    if (!canEdit) return <Tag className={className}>{content}</Tag>;

    function start() {
        setDraft(value);
        setError('');
        setEditing(true);
    }

    function cancel(refocus = false) {
        returnFocus.current = refocus;
        setError('');
        setEditing(false);
    }

    async function save() {
        if (saving) return;
        const title = draft.trim();
        if (!title) return setError('Название не может быть пустым.');
        if (title.length > MAX_TITLE_LENGTH) return setError(`Название не длиннее ${MAX_TITLE_LENGTH} символов.`);
        if (title === value) return cancel(true);
        setSaving(true);
        setError('');
        try {
            await onSave(title);
            cancel(true);
        } catch (err) {
            console.error('Failed to rename:', err);
            setError(saveErrorMessage(err));
            inputRef.current?.focus();
        } finally {
            setSaving(false);
        }
    }

    function handleKeyDown(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            save();
        } else if (e.key === 'Escape') {
            e.stopPropagation();
            cancel(true);
        }
    }

    if (editing) {
        return (
            <div className="editable-title editable-title--editing">
                <input
                    ref={inputRef}
                    className="input"
                    type="text"
                    aria-label="Название"
                    aria-invalid={error ? 'true' : undefined}
                    maxLength={MAX_TITLE_LENGTH}
                    value={draft}
                    disabled={saving}
                    onChange={e => { setDraft(e.target.value); setError(''); }}
                    onKeyDown={handleKeyDown}
                    onBlur={() => { if (!saving) cancel(); }}
                />
                {error && <p className="notice notice-danger" role="alert">{error}</p>}
            </div>
        );
    }

    return (
        <div className="editable-title">
            <Tag className={className}>{content}</Tag>
            <button
                ref={pencilRef}
                type="button"
                className="btn btn-ghost btn-sm editable-title__pencil"
                aria-label="Изменить название"
                title="Изменить название"
                onClick={start}
            >
                <span aria-hidden="true">✎</span>
            </button>
        </div>
    );
}

export default EditableTitle;
