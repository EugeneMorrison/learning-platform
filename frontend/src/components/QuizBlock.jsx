import { useState, useEffect, useRef } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import './QuizBlock.css';

hljs.registerLanguage('python', python);

function QuizBlock({ content }) {
    const [selected, setSelected] = useState(null);
    const [submitted, setSubmitted] = useState(false);

    const codeRef = useRef(null);
    const isCorrect = submitted && selected === content.correct_answer;

    useEffect(() => {
        if (codeRef.current) {
            hljs.highlightElement(codeRef.current);
            codeRef.current.style.background = 'transparent';
        }
    }, []);

    function handleSubmit() {
        if (selected !== null) {
            setSubmitted(true);
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

    // Split question into text + code parts
    const parts = content.question.split('\n\n');
    const hasCode = parts.length >= 2;
    const questionText = hasCode ? parts[0] : content.question;
    const codePart = hasCode ? parts.slice(1).join('\n') : null;

    return (
        <div className="quiz-block" style={{
            background: 'white',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            borderLeft: '4px solid #2563eb',
        }}>
            <p
                style={{ fontWeight: '600', marginBottom: codePart ? '12px' : '16px' }}
                dangerouslySetInnerHTML={{ __html: '❓ ' + questionText }}
            />
            {codePart && (
                <pre style={{
                    background: '#f0f0f0',
                    borderRadius: '6px',
                    padding: '14px 18px',
                    fontFamily: "'JetBrains Mono', Consolas, monospace",
                    fontSize: '14px',
                    lineHeight: '1.6',
                    marginBottom: '16px',
                    overflowX: 'auto',
                    whiteSpace: 'pre-wrap',
                    color: '#383a42',
                }}>
                    <code ref={codeRef} className="language-python">{codePart}</code>
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

            {/* Check Answer button — hidden only after correct answer */}
            {!isCorrect && (
                <button
                    onClick={submitted ? handleReset : handleSubmit}
                    disabled={!submitted && selected === null}
                    style={{
                        marginTop: '16px',
                        padding: '10px 24px',
                        background: submitted ? '#dc2626' : selected === null ? '#94a3b8' : '#2563eb',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: !submitted && selected === null ? 'not-allowed' : 'pointer',
                        fontWeight: '600',
                    }}
                >
                    {submitted ? 'Попробовать снова' : 'Проверить ответ'}
                </button>
            )}

            {/* Feedback */}
            {submitted && (
                <div style={{
                    marginTop: '16px',
                    padding: '12px',
                    borderRadius: '6px',
                    background: isCorrect ? '#dcfce7' : '#fee2e2',
                    color: isCorrect ? '#16a34a' : '#dc2626',
                    fontWeight: '600',
                }}>
                    {isCorrect ? '✅ Верно! ' + content.explanation : '❌ Неверно. Попробуй ещё раз!'}
                </div>
            )}

            {/* Solve again button — shown only after correct answer */}
            {isCorrect && (
                <button
                    onClick={handleReset}
                    style={{
                        marginTop: '12px',
                        padding: '10px 24px',
                        background: 'white',
                        color: '#2563eb',
                        border: '2px solid #2563eb',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontWeight: '600',
                    }}
                >
                    Решить снова
                </button>
            )}
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