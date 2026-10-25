import { useState } from 'react';
import api from '../api';
import './blocks.css';
import { DiscussionBadge } from './DiscussionPanel';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';
import { renderMath } from '../lib/contentMath';
import { parseTemplate } from '../lib/fillTemplate';

/**
 * "Fill in the blanks" task (Stepik-style). The author writes a code/text
 * template with blanks as {{answer}} (or {{a|b}} for alternatives). Students
 * receive the template with empty gaps ({{}}) — never the answers — type into
 * each gap, and the backend grades: is_correct, which gaps are right
 * (feedback.blanks_correct) and, when correct, the explanation.
 */

// Server verdict → component state.
function toResult(isCorrect, feedback) {
    return {
        isCorrect: isCorrect === true,
        blanksCorrect: feedback?.blanks_correct || [],
        explanation: feedback?.explanation || '',
    };
}

function FillBlock({ content, blockId, savedProgress, number, onSubmitted, onAsk, discussion }) {
    const segments = parseTemplate(content.template);
    const blanks = segments.filter(s => s.type === 'blank');

    const savedBlanks = savedProgress?.answer?.blanks;
    const hasAttempt = Array.isArray(savedBlanks);
    const [values, setValues] = useState(
        hasAttempt ? blanks.map((_, i) => savedBlanks[i] ?? '') : blanks.map(() => '')
    );
    // Restored on page load from the student's own saved progress.
    const [result, setResult] = useState(
        hasAttempt ? toResult(savedProgress.is_correct, savedProgress.feedback) : null
    );
    const [checking, setChecking] = useState(false);
    const [checkError, setCheckError] = useState('');

    const submitted = result !== null;
    const perBlankCorrect = blanks.map((_, i) => result?.blanksCorrect[i] === true);
    const isCorrect = result?.isCorrect === true;

    async function handleSubmit() {
        if (values.some(v => !v.trim()) || checking) return; // require all blanks filled
        setChecking(true);
        setCheckError('');
        try {
            const res = await api.post('/progress/submit/', {
                block: blockId,
                answer: { blanks: values },
            });
            setResult(toResult(res.data.is_correct, res.data.feedback));
            onSubmitted?.(res.data); // the lesson's progress (app header, "next task")
        } catch (err) {
            console.error('Failed to check answer:', err);
            setCheckError(err.response?.data?.detail || 'Не удалось проверить ответ. Попробуйте ещё раз.');
        } finally {
            setChecking(false);
        }
    }

    function handleReset() {
        setResult(null);
    }

    function setBlank(i, val) {
        setValues(prev => {
            const next = [...prev];
            next[i] = val;
            return next;
        });
    }

    const allFilled = values.every(v => v.trim());

    return (
        <div className={isCorrect ? 'lesson-block lesson-block--solved' : 'lesson-block'}>
            <div className="lesson-block__head">
                <span className="lesson-block__badge">Пропуски{number ? ` ${number}` : ''}</span>
                {isCorrect && <span className="lesson-block__solved">✓ Решено</span>}
                {onAsk && (
                    <button type="button" className="lesson-block__ask" onClick={() => onAsk()}>
                        Задать вопрос
                    </button>
                )}
                <DiscussionBadge blockId={blockId} discussion={discussion} />
            </div>

            {content.prompt && (
                <div
                    className="text-content lesson-block__prompt"
                    dangerouslySetInnerHTML={{ __html: wrapTables(wrapImages(renderMath(highlightPreBlocks(content.prompt)))) }}
                />
            )}

            <div className="lesson-block__label">Заполните пропуски:</div>

            {/* Text flows as plain text (author's line breaks preserved); only the
                blanks are bordered inputs that grow with what the student types. */}
            <div className="fill-template">
                {segments.map((seg, idx) => {
                    if (seg.type === 'text') return <span key={idx}>{seg.value}</span>;
                    const i = seg.index;
                    const ok = perBlankCorrect[i];
                    const chars = Math.max(5, values[i]?.length || 0);
                    return (
                        <input
                            key={idx}
                            type="text"
                            aria-label={`Пропуск ${i + 1}`}
                            className={submitted ? (ok ? 'fill-blank fill-blank--correct' : 'fill-blank fill-blank--wrong') : 'fill-blank'}
                            value={values[i]}
                            disabled={isCorrect}
                            onChange={e => { setBlank(i, e.target.value); if (submitted) setResult(null); }}
                            style={{ '--fill-chars': chars /* grows with the answer; width in blocks.css */ }}
                        />
                    );
                })}
            </div>

            {checkError && (
                <div className="check-error" role="alert">{checkError}</div>
            )}

            {submitted && (
                <div className={isCorrect ? 'verdict verdict--success' : 'verdict verdict--danger'} role="status">
                    {isCorrect ? '✅ Верно!' : '❌ Неверно! Проверьте заполнение и попробуйте ещё раз.'}
                    {isCorrect && result.explanation && (
                        <span className="verdict__detail"> {result.explanation}</span>
                    )}
                </div>
            )}

            {/* Action row, after the feedback (same as QUIZ). */}
            <div className="lesson-block__actions">
                <div className="lesson-block__actions-start">
                    <button
                        className="lesson-block__text-btn"
                        onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                    >
                        ↑ Вернуться к теории
                    </button>
                </div>
                <div className="lesson-block__actions-end">
                    {submitted ? (
                        <button className="btn btn-secondary" onClick={handleReset}>
                            {isCorrect ? 'Решить снова' : 'Попробовать снова'}
                        </button>
                    ) : (
                        <button
                            className="btn btn-primary"
                            onClick={handleSubmit}
                            disabled={!allFilled || checking}
                        >
                            {checking ? 'Проверяем…' : 'Проверить'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}

export default FillBlock;
