import { useState } from 'react';
import api from '../api';
import { highlightPreBlocks } from '../lib/pythonHighlight';
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

function FillBlock({ content, blockId, savedProgress, number }) {
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
        <div style={{
            background: 'white',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            borderLeft: '4px solid #c2410c',
        }}>
            <div style={{ marginBottom: '14px' }}>
                <span style={{
                    display: 'inline-block',
                    padding: '4px 12px',
                    background: '#ffedd5',
                    color: '#c2410c',
                    borderRadius: '999px',
                    fontWeight: '600',
                    letterSpacing: '0.3px',
                }}>
                    Пропуски{number ? ` ${number}` : ''}
                </span>
            </div>

            {content.prompt && (
                <div
                    className="text-content"
                    style={{ marginBottom: '16px' }}
                    dangerouslySetInnerHTML={{ __html: highlightPreBlocks(content.prompt) }}
                />
            )}

            <div style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '8px' }}>
                Заполните пропуски:
            </div>

            {/* Text flows as plain text (author's line breaks preserved); only the
                blanks are bordered inputs that grow with what the student types. */}
            <div style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                lineHeight: 2.2,
                fontFamily: "'JetBrains Mono', Consolas, monospace",
                fontSize: '14px',
                color: '#334155',
            }}>
                {segments.map((seg, idx) => {
                    if (seg.type === 'text') return <span key={idx}>{seg.value}</span>;
                    const i = seg.index;
                    const ok = perBlankCorrect[i];
                    const ch = Math.max(8, (values[i]?.length || 0) + 2);
                    return (
                        <input
                            key={idx}
                            type="text"
                            value={values[i]}
                            disabled={isCorrect}
                            onChange={e => { setBlank(i, e.target.value); if (submitted) setResult(null); }}
                            style={{
                                fontFamily: "'JetBrains Mono', Consolas, monospace",
                                fontSize: '14px',
                                padding: '4px 12px',
                                borderRadius: '999px',
                                border: '2px solid',
                                borderColor: submitted ? (ok ? '#16a34a' : '#dc2626') : '#c7d2fe',
                                background: submitted ? (ok ? '#dcfce7' : '#fee2e2') : '#eef2ff',
                                width: `${ch}ch`,
                                maxWidth: '100%',
                                outline: 'none',
                                verticalAlign: 'middle',
                            }}
                        />
                    );
                })}
            </div>

            {!submitted && (
                <button
                    onClick={handleSubmit}
                    disabled={!allFilled || checking}
                    style={{
                        marginTop: '16px',
                        padding: '10px 24px',
                        background: allFilled && !checking ? '#c2410c' : '#94a3b8',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: allFilled && !checking ? 'pointer' : 'not-allowed',
                        fontWeight: '600',
                    }}
                >
                    {checking ? 'Проверяем…' : 'Проверить'}
                </button>
            )}

            {checkError && (
                <div style={{ marginTop: '12px', color: '#dc2626' }}>{checkError}</div>
            )}

            {submitted && (
                <div style={{
                    marginTop: '16px',
                    padding: '12px',
                    borderRadius: '6px',
                    background: isCorrect ? '#dcfce7' : '#fee2e2',
                    color: isCorrect ? '#16a34a' : '#dc2626',
                    fontWeight: '600',
                }}>
                    {isCorrect
                        ? ('✅ Верно!' + (result.explanation ? ' ' + result.explanation : ''))
                        : '❌ Неверно! Проверьте заполнение и попробуйте ещё раз.'}
                </div>
            )}

            {submitted && (
                <button
                    onClick={handleReset}
                    style={{
                        marginTop: '12px',
                        padding: '10px 24px',
                        background: 'white',
                        color: '#475569',
                        border: '1px solid #cbd5e1',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontWeight: '600',
                    }}
                >
                    {isCorrect ? 'Решить снова' : 'Попробовать снова'}
                </button>
            )}
        </div>
    );
}

export default FillBlock;
