import { useState } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import './blocks.css';
import api from '../api';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages } from '../lib/contentImages';

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
        <div className={isCorrect ? 'lesson-block lesson-block--solved' : 'lesson-block'}>
            <div className="lesson-block__head">
                <span className="lesson-block__badge">Тест{number ? ` ${number}` : ''}</span>
                {isCorrect && <span className="lesson-block__solved">✓ Решено</span>}
            </div>

            {htmlQuestion ? (
                <div
                    className="text-content lesson-block__prompt"
                    dangerouslySetInnerHTML={{ __html: wrapImages(highlightPreBlocks(content.question)) }}
                />
            ) : (
                <>
                    <p
                        className="quiz-question"
                        dangerouslySetInnerHTML={{ __html: '❓ ' + questionText }}
                    />
                    {codePart && (
                        <pre className="code-sample">
                            <code
                                className="hljs language-python"
                                dangerouslySetInnerHTML={{ __html: highlightedCode }}
                            />
                        </pre>
                    )}
                </>
            )}

            <div className={isCorrect ? 'quiz-options quiz-options--locked' : 'quiz-options'}>
                {content.options.map((option, index) => (
                    <button
                        key={index}
                        onClick={() => handleOptionClick(index)}
                        className={optionClass(index, selected, submitted, isCorrect)}
                        dangerouslySetInnerHTML={{ __html: option }}
                    />
                ))}
            </div>

            {/* Check Answer button — shown before submission */}
            {!submitted && (
                <div className="lesson-block__actions">
                    <button
                        className="btn btn-primary"
                        onClick={handleSubmit}
                        disabled={selected === null || checking}
                    >
                        {checking ? 'Проверяем…' : 'Проверить ответ'}
                    </button>
                </div>
            )}

            {checkError && (
                <div className="check-error" role="alert">{checkError}</div>
            )}

            {/* Feedback — always appears before the retry/solve button */}
            {submitted && (
                <div className={isCorrect ? 'verdict verdict--success' : 'verdict verdict--danger'} role="status">
                    {isCorrect ? '✅ Верно!' : '❌ Неверно! Попробуйте еще раз!'}
                    {isCorrect && result.explanation && (
                        <span className="verdict__detail"> {result.explanation}</span>
                    )}
                </div>
            )}

            {/* Retry / Solve again button — after feedback in both cases */}
            {submitted && (
                <div className="lesson-block__actions">
                    <button className="btn btn-secondary" onClick={handleReset}>
                        {isCorrect ? 'Решить снова' : 'Попробовать снова'}
                    </button>
                </div>
            )}

            <button
                className="lesson-block__text-btn"
                onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            >
                ↑ Вернуться к теории
            </button>
        </div>
    );
}

// Only the selected option is coloured after checking (green if the server said
// correct, red otherwise); the correct option is never revealed.
function optionClass(index, selected, submitted, isCorrect) {
    if (index !== selected) return 'quiz-option';
    if (!submitted) return 'quiz-option quiz-option--selected';
    return isCorrect ? 'quiz-option quiz-option--correct' : 'quiz-option quiz-option--wrong';
}

export default QuizBlock;