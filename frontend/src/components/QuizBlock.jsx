import { useState } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import './blocks.css';
import { DiscussionBadge } from './DiscussionPanel';
import api from '../api';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';
import { renderMath } from '../lib/contentMath';
import { reshuffleOptions, restoreQuiz } from '../lib/quizState';

hljs.registerLanguage('python', python);

// Questions authored with the rich-text editor are HTML (wrapped in block tags);
// older quizzes store plain text with an optional "\n\n + code" convention.
function isHtmlQuestion(q) {
    return /<(p|h[1-6]|ul|ol|li|pre|blockquote|img|table|strong|em|code|div|br)\b/i.test(q || '');
}

function QuizBlock({ content, blockId, quizRevision, savedProgress, number, onSubmitted, onAsk, discussion }) {
    // Retain the first saved completion independently of temporary practice.
    const [initial, setInitial] = useState(() => restoreQuiz(content, savedProgress, quizRevision));
    const [practice, setPractice] = useState(false);
    const shown = !practice && initial.snapshot ? initial.snapshot : content;
    const multiple = shown.multiple_answers === true;
    const shuffle = content.shuffle_options !== false;
    const [order, setOrder] = useState(initial.order);
    const [selected, setSelected] = useState(initial.selected);
    const [result, setResult] = useState(initial.result);
    const [checking, setChecking] = useState(false);
    const [checkError, setCheckError] = useState('');

    const submitted = result !== null;
    const isCorrect = result?.isCorrect === true;

    const htmlQuestion = isHtmlQuestion(shown.question);

    // Legacy plain-text format: split question into text + code parts.
    const parts = shown.question.split('\n\n');
    const hasCode = !htmlQuestion && parts.length >= 2;
    const questionText = hasCode ? parts[0] : shown.question;
    const codePart = hasCode ? parts.slice(1).join('\n') : null;
    const highlightedCode = codePart
        ? hljs.highlight(codePart, { language: 'python', ignoreIllegals: true }).value
        : '';

    async function handleSubmit() {
        if (selected === null || (Array.isArray(selected) && selected.length === 0) || checking) return;
        setChecking(true);
        setCheckError('');
        try {
            const res = await api.post('/progress/submit/', {
                block: blockId,
                answer: {
                    selected,
                    display_order: order.map(option => option.originalIndex),
                    quiz_revision: quizRevision,
                },
            });
            if (res.data.is_correct === true && res.data.recorded) {
                const completion = restoreQuiz(content, res.data, quizRevision);
                setInitial(completion);
                showCompletion(completion);
            } else {
                setResult({
                    isCorrect: res.data.is_correct === true,
                    explanation: res.data.feedback?.explanation || '',
                });
            }
            onSubmitted?.(res.data); // the lesson's progress (app header, "next task")
        } catch (err) {
            console.error('Failed to check answer:', err);
            setCheckError(err.response?.data?.detail || 'Не удалось проверить ответ. Попробуйте ещё раз.');
        } finally {
            setChecking(false);
        }
    }

    function showCompletion(completion) {
        setPractice(false);
        setOrder(completion.order);
        setSelected(completion.selected);
        setResult(completion.result);
        setCheckError('');
    }

    function handleReset() {
        if (checking) return;
        if (initial.result?.isCorrect) setPractice(true);
        // Retry uses today's options, with a different text order when possible.
        // The first saved success remains separate from this practice order.
        setOrder(reshuffleOptions(content.options, shuffle, order));
        setSelected(null);
        setResult(null);
        setCheckError('');
    }

    function handleOptionClick(index) {
        // A verdict ends this attempt; the retry action starts the next one.
        if (submitted || checking) return;
        setSelected(previous => multiple
            ? (previous || []).includes(index)
                ? previous.filter(value => value !== index) : [...(previous || []), index]
            : index);
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

            {!practice && initial.historical && (
                <p className="lesson-block__label">Показана версия задания на момент вашего решения</p>
            )}
            {!practice && initial.legacyChanged && (
                <p className="lesson-block__label">Задание изменено; варианты на момент вашего решения не сохранены.</p>
            )}
            {practice && (
                <p className="lesson-block__label">Тренировка. Сохранённое решение не изменится.</p>
            )}

            {htmlQuestion ? (
                <div
                    className="text-content lesson-block__prompt"
                    dangerouslySetInnerHTML={{ __html: wrapTables(wrapImages(renderMath(highlightPreBlocks(shown.question)))) }}
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

            {multiple && <p className="lesson-block__label">Выберите все правильные варианты ответа.</p>}
            <div className={isCorrect ? 'quiz-options quiz-options--locked' : 'quiz-options'}>
                {order.map(({ text, originalIndex }) => (
                    <button
                        key={originalIndex}
                        type="button"
                        aria-pressed={Array.isArray(selected) ? selected.includes(originalIndex) : selected === originalIndex}
                        disabled={checking || submitted}
                        onClick={() => handleOptionClick(originalIndex)}
                        className={optionClass(originalIndex, selected, submitted, isCorrect)}
                    >
                        {multiple && <span aria-hidden="true" style={{ marginRight: 8 }}>{selected?.includes(originalIndex) ? '☑' : '☐'}</span>}
                        <span dangerouslySetInnerHTML={{ __html: text }} />
                    </button>
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
                    {practice && initial.result?.isCorrect && (
                        <button className="btn btn-secondary" disabled={checking} onClick={() => showCompletion(initial)}>
                            Вернуться к сохранённому решению
                        </button>
                    )}
                    {submitted ? (
                        <button className="btn btn-secondary" onClick={handleReset}>
                            {isCorrect ? 'Решить снова' : 'Попробовать снова'}
                        </button>
                    ) : (
                        <button
                            className="btn btn-primary"
                            onClick={handleSubmit}
                            disabled={selected === null || (Array.isArray(selected) && selected.length === 0) || checking}
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
    if (!(Array.isArray(selected) ? selected.includes(index) : index === selected)) return 'quiz-option';
    if (!submitted) return 'quiz-option quiz-option--selected';
    return isCorrect ? 'quiz-option quiz-option--correct' : 'quiz-option quiz-option--wrong';
}

export default QuizBlock;
