import { useState } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import './QuizBlock.css';
import api from '../api';
import { highlightPreBlocks } from '../lib/pythonHighlight';

hljs.registerLanguage('python', python);

// Questions authored with the rich-text editor are HTML (wrapped in block tags);
// older quizzes store plain text with an optional "\n\n + code" convention.
function isHtmlQuestion(q) {
    return /<(p|h[1-6]|ul|ol|li|pre|blockquote|img|strong|em|code|div|br)\b/i.test(q || '');
}

function QuizBlock({ content, blockId, savedProgress, number }) {
    const savedSelected = savedProgress?.answer?.selected;
    const hasAttempt = typeof savedSelected === 'number';
    const [selected, setSelected] = useState(hasAttempt ? savedSelected : null);
    // The server's verdict on `selected` (students never receive correct_answer).
    // Restored on page load from the student's own saved progress.
    const [result, setResult] = useState(hasAttempt ? {
        isCorrect: savedProgress.is_correct === true,
        explanation: savedProgress.feedback?.explanation || '',
    } : null);
    const [checking, setChecking] = useState(false);
    const [checkError, setCheckError] = useState('');

    const submitted = result !== null;
    const isCorrect = result?.isCorrect === true;

    const htmlQuestion = isHtmlQuestion(content.question);

    // Legacy plain-text format: split question into text + code parts.
    const parts = content.question.split('\n\n');
    const hasCode = !htmlQuestion && parts.length >= 2;
    const questionText = hasCode ? parts[0] : content.question;
    const codePart = hasCode ? parts.slice(1).join('\n') : null;
    const highlightedCode = codePart
        ? hljs.highlight(codePart, { language: 'python', ignoreIllegals: true }).value
        : '';

    async function handleSubmit() {
        if (selected === null || checking) return;
        setChecking(true);
        setCheckError('');
        try {
            const res = await api.post('/progress/submit/', {
                block: blockId,
                answer: { selected },
            });
            setResult({
                isCorrect: res.data.is_correct === true,
                explanation: res.data.feedback?.explanation || '',
            });
        } catch (err) {
            console.error('Failed to check answer:', err);
            setCheckError(err.response?.data?.detail || 'Не удалось проверить ответ. Попробуйте ещё раз.');
        } finally {
            setChecking(false);
        }
    }

    function handleReset() {
        setSelected(null);
        setResult(null);
    }

    function handleOptionClick(index) {
        // Only allow clicking if correct answer not yet found
        if (isCorrect) return;
        setSelected(index);
        setResult(null);
    }

    return (
        <div className="quiz-block" style={{
            background: 'white',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            borderLeft: '4px solid #2563eb',
        }}>
            {/* Block type badge */}
            <div style={{ marginBottom: '14px' }}>
                <span style={{
                    display: 'inline-block',
                    padding: '4px 12px',
                    background: '#ede9fe',
                    color: '#6d28d9',
                    borderRadius: '999px',
                    fontWeight: '600',
                    letterSpacing: '0.3px',
                }}>
                    Тест{number ? ` ${number}` : ''}
                </span>
            </div>

            {htmlQuestion ? (
                <div
                    className="text-content"
                    style={{ marginBottom: '16px' }}
                    dangerouslySetInnerHTML={{ __html: highlightPreBlocks(content.question) }}
                />
            ) : (
                <>
                    <p
                        style={{ fontWeight: '600', marginBottom: codePart ? '12px' : '16px' }}
                        dangerouslySetInnerHTML={{ __html: '❓ ' + questionText }}
                    />
                    {codePart && (
                        <pre style={{
                            background: '#f0f0f0',
                            borderRadius: '6px',
                            padding: '10px 16px',
                            fontFamily: "'JetBrains Mono', Consolas, monospace",
                            fontSize: '14px',
                            lineHeight: '1.6',
                            marginBottom: '12px',
                            overflowX: 'auto',
                            whiteSpace: 'pre-wrap',
                            color: '#383a42',
                        }}>
                            <code
                                className="hljs language-python"
                                style={{ background: 'transparent' }}
                                dangerouslySetInnerHTML={{ __html: highlightedCode }}
                            />
                        </pre>
                    )}
                </>
            )}

            <div className="quiz-options" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {content.options.map((option, index) => (
                    <button
                        key={index}
                        onClick={() => handleOptionClick(index)}
                        style={{
                            padding: '10px 16px',
                            borderRadius: '6px',
                            border: '2px solid',
                            cursor: isCorrect ? 'default' : 'pointer',
                            textAlign: 'left',
                            background: getOptionBackground(index, selected, submitted, isCorrect),
                            borderColor: getOptionBorder(index, selected, submitted, isCorrect),
                            fontWeight: index === selected ? '600' : 'normal',
                            fontFamily: "'JetBrains Mono', Consolas, monospace",
                            fontSize: '14px',
                        }}
                        dangerouslySetInnerHTML={{ __html: option }}
                    />
                ))}
            </div>

            {/* Check Answer button — shown before submission */}
            {!submitted && (
                <button
                    onClick={handleSubmit}
                    disabled={selected === null || checking}
                    style={{
                        marginTop: '16px',
                        padding: '10px 24px',
                        background: selected === null || checking ? '#94a3b8' : '#2563eb',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: selected === null || checking ? 'not-allowed' : 'pointer',
                        fontWeight: '600',
                    }}
                >
                    {checking ? 'Проверяем…' : 'Проверить ответ'}
                </button>
            )}

            {checkError && (
                <div style={{ marginTop: '12px', color: '#dc2626' }}>{checkError}</div>
            )}

            {/* Feedback — always appears before the retry/solve button */}
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
                        ? '✅ Верно!' + (result.explanation ? ' ' + result.explanation : '')
                        : '❌ Неверно! Попробуйте еще раз!'}
                </div>
            )}

            {/* Retry / Solve again button — after feedback in both cases */}
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

            <button
                onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                style={{
                    display: 'block',
                    marginTop: '16px',
                    padding: '0',
                    background: 'none',
                    border: 'none',
                    color: '#64748b',
                    fontSize: '13px',
                    cursor: 'pointer',
                    textDecoration: 'underline',
                }}
            >
                ↑ Вернуться к теории
            </button>
        </div>
    );
}

// Only the selected option is coloured after checking (green if the server said
// correct, red otherwise); the correct option is never revealed.
function getOptionBackground(index, selected, submitted, isCorrect) {
    if (submitted && index === selected) return isCorrect ? '#dcfce7' : '#fee2e2';
    if (index === selected) return '#eff6ff';
    return 'white';
}

function getOptionBorder(index, selected, submitted, isCorrect) {
    if (submitted && index === selected) return isCorrect ? '#16a34a' : '#dc2626';
    if (index === selected) return '#2563eb';
    return '#e2e8f0';
}

export default QuizBlock;