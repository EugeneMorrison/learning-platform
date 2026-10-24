import { useEffect, useRef, useState } from 'react';
import api from '../api';
import './CourseCoverEditor.css';

// The server's limits (api/serializers.py: MAX_COVER_BYTES, COVER_FORMATS),
// checked here first so a wrong file fails at once, before any upload. The
// server checks again (by content, not by the browser's type) and shrinks the
// saved cover to 1200 px wide WebP (api/covers.py).
const MAX_BYTES = 10 * 1024 * 1024;
const TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
const TOO_BIG = 'Файл больше 10 МБ. Уменьшите изображение.';
const WRONG_TYPE = 'Этот формат не подходит. Подойдут JPEG, PNG, WebP или GIF.';

// Server message for a rejected upload ({"cover": ["..."]}), else the fallback.
// 413 comes from nginx (request body over its limit) before Django sees it.
function saveErrorMessage(err, fallback) {
    if (err.response?.status === 413) return TOO_BIG;
    const data = err.response?.data;
    return data?.cover?.[0] || data?.detail || fallback;
}

/**
 * The course cover on the course page, for its owner: upload, replace or
 * remove. A chosen file is shown first in the card's 4:3 box (as the catalog
 * will crop it) and saved only on «Сохранить обложку» (multipart PATCH).
 * onSaved(coverUrlOrNull) gets the server's answer.
 */
function CourseCoverEditor({ courseId, cover, onSaved }) {
    const [pending, setPending] = useState(null); // { file, url }: chosen, not saved yet
    const [saving, setSaving] = useState(false);
    const [status, setStatus] = useState(''); // '' | 'saved' | 'removed'
    const [error, setError] = useState('');
    const inputRef = useRef(null);
    const chooseRef = useRef(null);

    // The preview's object URL is freed when it's replaced, dropped or the page closes.
    useEffect(() => () => {
        if (pending) URL.revokeObjectURL(pending.url);
    }, [pending]);

    function handleChoose(e) {
        const file = e.target.files[0];
        e.target.value = ''; // choosing the same file again fires change again
        if (!file) return;
        setStatus('');
        if (!TYPES.includes(file.type)) {
            setError(WRONG_TYPE);
            return;
        }
        if (file.size > MAX_BYTES) {
            setError(TOO_BIG);
            return;
        }
        setError('');
        setPending({ file, url: URL.createObjectURL(file) });
    }

    async function save(body, doneStatus, fallback) {
        setSaving(true);
        setError('');
        setStatus('');
        try {
            const res = await api.patch(`/courses/${courseId}/`, body);
            onSaved(res.data.cover);
            setPending(null);
            setStatus(doneStatus);
            chooseRef.current?.focus(); // the save / remove button is gone: keep focus nearby
        } catch (err) {
            console.error('Failed to save course cover:', err);
            setError(saveErrorMessage(err, fallback));
        } finally {
            setSaving(false);
        }
    }

    function handleSave() {
        const data = new FormData();
        data.append('cover', pending.file);
        save(data, 'saved', 'Не удалось сохранить обложку. Попробуйте ещё раз.');
    }

    function handleRemove() {
        if (!window.confirm('Удалить обложку курса?')) return;
        save({ cover: null }, 'removed', 'Не удалось удалить обложку. Попробуйте ещё раз.');
    }

    const shown = pending ? pending.url : cover;

    return (
        <div className="cover-editor">
            <span className="cover-editor__label">Обложка</span>
            <div className="cover-editor__row">
                <div className="cover-editor__preview">
                    {shown ? (
                        <img src={shown} alt={pending ? 'Новая обложка, ещё не сохранена' : 'Обложка курса'} />
                    ) : (
                        <span className="cover-editor__empty">Нет обложки</span>
                    )}
                    {pending && <span className="cover-editor__unsaved" aria-hidden="true">Не сохранено</span>}
                </div>

                <div className="cover-editor__side">
                    <div className="cover-editor__actions">
                        {pending ? (
                            <>
                                <button type="button" className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
                                    {saving ? 'Сохранение…' : 'Сохранить обложку'}
                                </button>
                                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPending(null)} disabled={saving}>
                                    Отмена
                                </button>
                            </>
                        ) : (
                            <>
                                <button
                                    type="button"
                                    ref={chooseRef}
                                    className="btn btn-secondary btn-sm"
                                    onClick={() => inputRef.current.click()}
                                    disabled={saving}
                                >
                                    {cover ? 'Заменить обложку' : 'Загрузить обложку'}
                                </button>
                                {cover && (
                                    <button type="button" className="btn btn-danger btn-sm" onClick={handleRemove} disabled={saving}>
                                        {saving ? 'Удаление…' : 'Удалить'}
                                    </button>
                                )}
                            </>
                        )}
                        <input ref={inputRef} type="file" accept={TYPES.join(',')} hidden onChange={handleChoose} />
                    </div>
                    <p className="cover-editor__hint">JPEG, PNG, WebP или GIF, до 10 МБ. Лучше 800×600 и только своя картинка.</p>
                    <p className={error ? 'cover-editor__status cover-editor__status--error' : 'cover-editor__status'} role="status">
                        {error
                            || (pending && 'Так обложка будет выглядеть в каталоге. Сохраните, чтобы применить.')
                            || (status === 'saved' && 'Обложка сохранена')
                            || (status === 'removed' && 'Обложка удалена')}
                    </p>
                </div>
            </div>
        </div>
    );
}

export default CourseCoverEditor;
