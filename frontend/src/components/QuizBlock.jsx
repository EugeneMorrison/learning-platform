import { useState } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import './blocks.css';
import { DiscussionBadge } from './DiscussionPanel';
import api from '../api';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';

hljs.registerLanguage('python', python);

// Questions authored with the rich-text editor are HTML (wrapped in block tags);
// older quizzes store plain text with an optional "\n\n + code" convention.
function isHtmlQuestion(q) {
    return /<(p|h[1-6]|ul|ol|li|pre|blockquote|img|table|strong|em|code|div|br)\b/i.test(q || '');
}

// The options in display order, each with its index in content.options (the
// index the server grades and progress stores). Fisher–Yates when shuffling.
function orderOptions(options, shuffle) {
    const order = options.map((text, originalIndex) => ({ text, originalIndex }));
    if (!shuffle) return order;
    for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
    }
    return order;
}

function QuizBlock({ content, blockId, savedProgress, number, onSubmitted, onAsk, discussion }) {
    // Missing shuffle_options = shuffle. The order is fixed on mount and changes
    // only on «Решить снова», never on a re-render.
    const shuffle = content.shuffle_options !== false;
    const [order, setOrder] = useState(() => orderOptions(content.options, shuffle));
    // `selected` is always an original index: sent as answer.selected and
    // restored from saved progress as is.
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
            onSubmitted?.(res.data); // the lesson's progress (app header, "next task")
        } catch (err) {
            console.error('Failed to check answer:', err);
            setCheckError(err.response?.data?.detail || 'Не удалось проверить ответ. Попробуйте ещё раз.');
        } finally {
            setChecking(false);
        }
    }

    function handleReset() {
        // «Решить снова» (after a correct answer) deals a new order;
        // «Попробовать снова» keeps the current one.
        if (isCorrect) setOrder(orderOptions(content.options, shuffle));
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
                {onAsk && (
                    <button type="button" className="lesson-block__ask" onClick={() => onAsk()}>
                        Задать вопрос
                    </button>
                )}
                <DiscussionBadge blockId={blockId} discussion={discussion} />
            </div>

            {htmlQuestion ? (
                <div
                    className="text-content lesson-block__prompt"
                    dangerouslySetInnerHTML={{ __html: wrapTables(wrapImages(highlightPreBlocks(content.question))) }}
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
                {order.map(({ text, originalIndex }) => (
                    <button
                        key={originalIndex}
                        onClick={() => handleOptionClick(originalIndex)}
                        className={optionClass(originalIndex, selected, submitted, isCorrect)}
                        dangerouslySetInnerHTML={{ __html: text }}
                    />
                ))}
            </div>

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

            {/* Action row, after the feedback: back to theory on the left; Check
                Answer (before submission) or Retry / Solve again on the right. */}
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
                            disabled={selected === null || checking}
                        >
                            {checking ? 'Проверяем…' : 'Проверить ответ'}
                        </button>
                    )}
                </div>
            </div>
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