import { useEffect, useRef, useState } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { CloseIcon } from './ChatPanel';
import './FormulaDialog.css';

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, [tabindex]:not([tabindex="-1"])';

// Quick inserts for authors who don't know LaTeX by heart. A command that
// ends in a letter gets a space after it, so \cdot x doesn't become \cdotx.
const SNIPPETS = [
    { label: 'a/b', latex: '\\frac{a}{b}', title: 'Дробь' },
    { label: 'x²', latex: 'x^{2}', title: 'Степень' },
    { label: 'xᵢ', latex: 'x_{i}', title: 'Нижний индекс' },
    { label: '√x', latex: '\\sqrt{x}', title: 'Квадратный корень' },
    { label: 'ⁿ√x', latex: '\\sqrt[n]{x}', title: 'Корень n-й степени' },
    { label: '·', latex: '\\cdot ', title: 'Умножение (точка)' },
    { label: '×', latex: '\\times ', title: 'Умножение (крестик)' },
    { label: '±', latex: '\\pm ', title: 'Плюс-минус' },
    { label: '≤', latex: '\\le ', title: 'Меньше или равно' },
    { label: '≥', latex: '\\ge ', title: 'Больше или равно' },
    { label: '≠', latex: '\\ne ', title: 'Не равно' },
    { label: '≈', latex: '\\approx ', title: 'Приблизительно равно' },
    { label: '∞', latex: '\\infty ', title: 'Бесконечность' },
    { label: 'π', latex: '\\pi ', title: 'Пи' },
    { label: 'α', latex: '\\alpha ', title: 'Альфа' },
    { label: 'Δ', latex: '\\Delta ', title: 'Дельта' },
    { label: '∑', latex: '\\sum_{i=1}^{n} ', title: 'Сумма' },
    { label: '|x|', latex: '\\left| x \\right|', title: 'Модуль' },
    { label: '(…)', latex: '\\left( x \\right)', title: 'Скобки по высоте содержимого' },
];

const PLACES = [
    { place: 'inline', label: 'В строке текста' },
    { place: 'left', label: 'Отдельной строкой, слева' },
    { place: 'center', label: 'Отдельной строкой, по центру' },
];

/**
 * The lesson editor's formula dialog: LaTeX with a live preview, quick-insert
 * buttons, and where the formula goes: PLACES (inside the line, or on a line
 * of its own, at the left or centred). Enter saves, Shift+Enter starts a new
 * line in the field.
 *
 * initial: { latex, place, editing }. onSubmit(latex, place); onDelete
 * (editing only); onClose.
 */
function FormulaDialog({ initial, onSubmit, onDelete, onClose }) {
    const [latex, setLatex] = useState(initial.latex || '');
    const [place, setPlace] = useState(initial.place || 'inline');
    const display = place !== 'inline';
    const dialogRef = useRef(null);
    const fieldRef = useRef(null);

    const trimmed = latex.trim();
    let preview = '';
    let error = '';
    if (trimmed) {
        try {
            preview = katex.renderToString(trimmed, { displayMode: display, throwOnError: true });
        } catch (err) {
            error = err instanceof katex.ParseError ? err.rawMessage || err.message : String(err);
        }
    }
    const canSubmit = !!trimmed && !error;

    // Focus the field (cursor at the end); lock the page behind.
    useEffect(() => {
        const field = fieldRef.current;
        field?.focus();
        field?.setSelectionRange(field.value.length, field.value.length);
        document.documentElement.classList.add('formula-dialog-open');
        return () => document.documentElement.classList.remove('formula-dialog-open');
    }, []);

    function insertSnippet(snippet) {
        const field = fieldRef.current;
        const start = field?.selectionStart ?? latex.length;
        const end = field?.selectionEnd ?? latex.length;
        const next = latex.slice(0, start) + snippet + latex.slice(end);
        setLatex(next);
        requestAnimationFrame(() => {
            field?.focus();
            field?.setSelectionRange(start + snippet.length, start + snippet.length);
        });
    }

    function submit() {
        if (canSubmit) onSubmit(trimmed, place);
    }

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

    return (
        <div className="formula-dialog-layer" onKeyDown={handleKeyDown}>
            <div className="formula-dialog__backdrop" onClick={onClose} aria-hidden="true" />
            <div ref={dialogRef} className="formula-dialog" role="dialog" aria-modal="true"
                aria-labelledby="formula-dialog-title">
                <div className="formula-dialog__head">
                    <h2 id="formula-dialog-title" className="formula-dialog__title">
                        {initial.editing ? 'Формула' : 'Новая формула'}
                    </h2>
                    <button type="button" className="btn btn-ghost btn-sm formula-dialog__close" onClick={onClose}
                        aria-label="Закрыть" title="Закрыть (Esc)">
                        <CloseIcon />
                    </button>
                </div>

                <div className="formula-dialog__body">
                    <div className="formula-dialog__snippets" role="group" aria-label="Вставить в формулу">
                        {SNIPPETS.map(s => (
                            <button key={s.latex} type="button" className="formula-dialog__snippet"
                                title={`${s.title}: ${s.latex.trim()}`} onClick={() => insertSnippet(s.latex)}>
                                {s.label}
                            </button>
                        ))}
                    </div>

                    <label className="formula-dialog__label" htmlFor="formula-dialog-latex">Формула в LaTeX</label>
                    <textarea
                        ref={fieldRef}
                        id="formula-dialog-latex"
                        className="input formula-dialog__field"
                        rows={3}
                        spellCheck={false}
                        value={latex}
                        onChange={e => setLatex(e.target.value)}
                        onKeyDown={e => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                submit();
                            }
                        }}
                        placeholder="Например: c = \sqrt{a^2 + b^2}"
                        aria-invalid={!!error || undefined}
                        aria-describedby="formula-dialog-preview"
                    />

                    <fieldset className="formula-dialog__where">
                        <legend className="visually-hidden">Где стоит формула</legend>
                        {PLACES.map(p => (
                            <label key={p.place}>
                                <input type="radio" name="formula-place" checked={place === p.place}
                                    onChange={() => setPlace(p.place)} />
                                {p.label}
                            </label>
                        ))}
                    </fieldset>

                    <div id="formula-dialog-preview" aria-live="polite"
                        className={`formula-dialog__preview${place === 'left' ? ' formula-dialog__preview--left' : ''}`}>
                        {!trimmed && <span className="formula-dialog__placeholder">Здесь появится формула</span>}
                        {preview && <div dangerouslySetInnerHTML={{ __html: preview }} />}
                        {error && <p className="formula-dialog__error" role="alert">Ошибка в формуле: {error}</p>}
                    </div>
                </div>

                <div className="formula-dialog__actions">
                    {initial.editing && (
                        <button type="button" className="btn btn-danger formula-dialog__delete" onClick={onDelete}>
                            Удалить формулу
                        </button>
                    )}
                    <button type="button" className="btn btn-secondary" onClick={onClose}>Отмена</button>
                    <button type="button" className="btn btn-primary" disabled={!canSubmit} onClick={submit}>
                        {initial.editing ? 'Сохранить' : 'Вставить'}
                    </button>
                </div>
            </div>
        </div>
    );
}

export default FormulaDialog;
