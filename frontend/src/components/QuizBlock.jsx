import { useState } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import './QuizBlock.css';
import api from '../api';

hljs.registerLanguage('python', python);

function QuizBlock({ content, blockId, savedProgress }) {
    const savedSelected = savedProgress?.answer?.selected;
    const hasAttempt = typeof savedSelected === 'number';
    const [selected, setSelected] = useState(hasAttempt ? savedSelected : null);
    const [submitted, setSubmitted] = useState(hasAttempt);

    const isCorrect = submitted && selected === content.correct_answer;

    // Split question into text + code parts
    const parts = content.question.split('\n\n');
    const hasCode = parts.length >= 2;
    const questionText = hasCode ? parts[0] : content.question;
    const codePart = hasCode ? parts.slice(1).join('\n') : null;
    const highlightedCode = codePart
        ? hljs.highlight(codePart, { language: 'python', ignoreIllegals: true }).value
        : '';

    async function handleSubmit() {
        if (selected === null) return;
        setSubmitted(true);
        try {
            await api.post('/progress/submit/', {
                block: blockId,
                answer: { selected },
            });
        } catch (err) {
            console.error('Failed to save progress:', err);
        }
    }

    function handleReset() {
        setSelected(null);
        setSubmitted(false);
    }

    function handleOptionClick(index) {
        // Only allow clicking if correct answer not yet found
        if (isCorrect) return;
        setSelected(index);
        setSubmitted(false);
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
                    Тест
                </span>
            </div>

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
                            background: getOptionBackground(index, selected, submitted, content.correct_answer),
                            borderColor: getOptionBorder(index, selected, submitted, content.correct_answer),
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
                    disabled={selected === null}
                    style={{
                        marginTop: '16px',
                        padding: '10px 24px',
                        background: selected === null ? '#94a3b8' : '#2563eb',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: selected === null ? 'not-allowed' : 'pointer',
                        fontWeight: '600',
                    }}
                >
                    Проверить ответ
                </button>
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
                    {isCorrect ? '✅ Верно! ' + content.explanation : '❌ Неверно! Попробуйте еще раз!'}
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

function getOptionBackground(index, selected, submitted, correct) {
    if (submitted && index === correct && index === selected) return '#dcfce7';
    if (submitted && index === selected && index !== correct) return '#fee2e2';
    if (index === selected) return '#eff6ff';
    return 'white';
}

function getOptionBorder(index, selected, submitted, correct) {
    if (submitted && index === correct && index === selected) return '#16a34a';
    if (submitted && index === selected && index !== correct) return '#dc2626';
    if (index === selected) return '#2563eb';
    return '#e2e8f0';
}

export default QuizBlock;