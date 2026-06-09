import { useState } from 'react';
import api from '../api';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { parseTemplate } from '../lib/fillTemplate';

/**
 * "Fill in the blanks" task (Stepik-style). The author writes a code/text
 * template with blanks as {{answer}} (or {{a|b}} for alternatives). Students
 * type into each blank; we grade client-side for instant feedback and also
 * POST to the backend, which re-grades and records the attempt.
 */

function matches(value, answers, caseSensitive) {
    const v = (value || '').trim();
    return answers.some(a => (caseSensitive ? a === v : a.toLowerCase() === v.toLowerCase()));
}

function FillBlock({ content, blockId, savedProgress, number }) {
    const segments = parseTemplate(content.template);
    const blanks = segments.filter(s => s.type === 'blank');
    const caseSensitive = !!content.case_sensitive;

    const savedBlanks = savedProgress?.answer?.blanks;
    const hasAttempt = Array.isArray(savedBlanks);
    const [values, setValues] = useState(
        hasAttempt ? blanks.map((_, i) => savedBlanks[i] ?? '') : blanks.map(() => '')
    );
    const [submitted, setSubmitted] = useState(hasAttempt);

    const perBlankCorrect = blanks.map((b, i) => matches(values[i], b.answers, caseSensitive));
    const allCorrect = perBlankCorrect.every(Boolean);
    const isCorrect = submitted && allCorrect;

    async function handleSubmit() {
        if (values.some(v => !v.trim())) return; // require all blanks filled
        setSubmitted(true);
        try {
            await api.post('/progress/submit/', {
                block: blockId,
                answer: { blanks: values },
            });
        } catch (err) {
            console.error('Failed to save progress:', err);
        }
    }

    function handleReset() {
        setSubmitted(false);
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
                            onChange={e => { setBlank(i, e.target.value); if (submitted) setSubmitted(false); }}
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
                    disabled={!allFilled}
                    style={{
                        marginTop: '16px',
                        padding: '10px 24px',
                        background: allFilled ? '#c2410c' : '#94a3b8',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: allFilled ? 'pointer' : 'not-allowed',
                        fontWeight: '600',
                    }}
                >
                    Проверить
                </button>
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
                        ? ('✅ Верно!' + (content.explanation ? ' ' + content.explanation : ''))
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
