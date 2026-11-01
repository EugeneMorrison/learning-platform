import { useEffect, useRef, useState } from 'react';
import './CourseDescriptionEditor.css';

function CourseDescriptionEditor({ value = '', canEdit, onSave }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(value);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const textareaRef = useRef(null);
    const buttonRef = useRef(null);
    const returnFocus = useRef(false);

    useEffect(() => {
        if (editing) textareaRef.current?.focus();
        else if (returnFocus.current) {
            buttonRef.current?.focus();
            returnFocus.current = false;
        }
    }, [editing]);

    function close() {
        returnFocus.current = true;
        setEditing(false);
        setError('');
    }

    async function save(event) {
        event.preventDefault();
        if (saving) return;
        setSaving(true);
        setError('');
        try {
            await onSave(draft.trim());
            close();
        } catch (err) {
            const errors = err.response?.data?.description;
            setError((Array.isArray(errors) ? errors.join(' ') : errors)
                || err.response?.data?.detail || 'Не удалось сохранить описание. Попробуйте ещё раз.');
        } finally {
            setSaving(false);
        }
    }

    if (!canEdit) return value ? <p className="page__lead course-description__text">{value}</p> : null;

    return (
        <section className="course-description" aria-label="Описание курса">
            <div className="course-description__head">
                <h2 className="course-description__title">Описание курса</h2>
                {!editing && <button ref={buttonRef} type="button" className="btn btn-secondary btn-sm"
                    onClick={() => { setDraft(value); setError(''); setEditing(true); }}>
                    {value ? 'Редактировать описание' : '+ Добавить описание'}
                </button>}
            </div>
            {editing ? (
                <form className="course-description__form" onSubmit={save}>
                    <label className="visually-hidden" htmlFor="course-description">Описание курса</label>
                    <textarea ref={textareaRef} id="course-description" className="input" rows={5}
                        value={draft} disabled={saving} placeholder="Расскажите, чему научатся студенты на этом курсе"
                        onChange={event => { setDraft(event.target.value); setError(''); }}
                        aria-invalid={Boolean(error)} aria-describedby={error ? 'course-description-error' : undefined} />
                    {error && <p id="course-description-error" className="notice notice-danger" role="alert">{error}</p>}
                    <div className="course-description__actions">
                        <button type="submit" className="btn btn-primary btn-sm" disabled={saving || draft.trim() === value}>
                            {saving ? 'Сохранение…' : 'Сохранить'}
                        </button>
                        <button type="button" className="btn btn-secondary btn-sm" disabled={saving} onClick={close}>Отмена</button>
                    </div>
                </form>
            ) : (
                <p className={value ? 'page__lead course-description__text' : 'course-description__empty'}>
                    {value || 'Описание пока не добавлено.'}
                </p>
            )}
        </section>
    );
}

export default CourseDescriptionEditor;
