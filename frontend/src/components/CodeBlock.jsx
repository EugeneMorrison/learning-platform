import { useState, useEffect, useRef } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { pycharmDarcula } from './pycharmDarcula';
import { wrapImages } from '../lib/contentImages';
import api from '../api';
import './blocks.css';

const PYTHON_VERSIONS = ['Python 3.10', 'Python 3.12'];

function CodeBlock({ blockId, content, savedProgress, number }) {
    const wasSolved = savedProgress?.is_correct === true;
    const savedCode = savedProgress?.answer?.code;

    const firstTest = content.tests?.[0];
    const firstTestInput = firstTest
        ? (typeof firstTest === 'object' ? firstTest.input : firstTest)
        : '';
    const hasTests = content.tests?.length > 0;
    // Students get only the visible tests; the server says how many are hidden.
    const hiddenTestCount = content.hidden_test_count || 0;
    const totalTestCount = (content.tests?.length || 0) + hiddenTestCount;

    const [userCode, setUserCode] = useState(savedCode || content.starter_code);
    const [testsOpen, setTestsOpen] = useState(true);
    const [testInput, setTestInput] = useState(firstTestInput || '');
    const [selectedTestIndex, setSelectedTestIndex] = useState(hasTests ? 0 : null);
    const [runOutput, setRunOutput] = useState(null);
    const [submitResults, setSubmitResults] = useState(
        wasSolved
            ? { status: 'success', total: totalTestCount }
            : null
    );
    const [isRunning, setIsRunning] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [hasSubmitted, setHasSubmitted] = useState(wasSolved);
    const [pythonVersion, setPythonVersion] = useState('Python 3.12');
    const [versionOpen, setVersionOpen] = useState(false);
    const versionRef = useRef(null);

    useEffect(() => {
        function handleClickOutside(e) {
            if (versionRef.current && !versionRef.current.contains(e.target)) {
                setVersionOpen(false);
            }
        }
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    function handleTestCheck(index) {
        if (selectedTestIndex === index) {
            setSelectedTestIndex(null);
            setTestInput('');
            return;
        }
        const test = content.tests[index];
        const input = typeof test === 'object' ? test.input : test;
        setSelectedTestIndex(index);
        setTestInput(input || '');
    }

    // "Запустить код" — runs against student's custom input
    const handleRun = async () => {
        setIsRunning(true);
        setRunOutput(null);
        try {
            const res = await api.post('/run-code/', {
                block_id: blockId,
                code: userCode,
                stdin: testInput,
                version: pythonVersion,
            });
            setRunOutput(res.data);
        } catch (err) {
            setRunOutput({
                stdout: '',
                // runner errors use "error"; DRF's 401/429 use "detail"
                stderr: err.response?.data?.error || err.response?.data?.detail || err.message || 'Ошибка соединения',
            });
        } finally {
            setIsRunning(false);
        }
    };

    // "Отправить" — the server runs the block's stored tests (hidden ones too),
    // decides whether it's solved and saves the progress itself.
    const handleSubmit = async () => {
        setIsSubmitting(true);
        setSubmitResults(null);
        setHasSubmitted(true);
        try {
            const res = await api.post('/run-tests/', {
                block_id: blockId,
                code: userCode,
                version: pythonVersion,
            });
            setSubmitResults(res.data);
        } catch (err) {
            setSubmitResults({
                status: 'error',
                // runner errors use "error"; DRF's 401/429 use "detail"
                stderr: err.response?.data?.error || err.response?.data?.detail || err.message || 'Ошибка соединения',
            });
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleReset = () => {
        setUserCode(content.starter_code);
        setTestInput(firstTestInput || '');
        setSelectedTestIndex(hasTests ? 0 : null);
        setRunOutput(null);
        setSubmitResults(null);
        setHasSubmitted(false);
    };

    const isSolved = submitResults?.status === 'success';

    return (
        <div className={isSolved ? 'lesson-block lesson-block--solved' : 'lesson-block'}>
            {/* Block type badge */}
            <div className="lesson-block__head">
                <span className="lesson-block__badge">Задача{number ? ` ${number}` : ''}</span>
                {isSolved && <span className="lesson-block__solved">✓ Решено</span>}
            </div>

            {/* Task prompt */}
            <div
                className="text-content lesson-block__prompt"
                dangerouslySetInnerHTML={{ __html: wrapImages(content.prompt) }}
            />

            {/* Collapsible tests table, open on load. Line breaks in the data are
                kept (pre-wrap); a wide table scrolls inside its own box. */}
            {content.tests && content.tests.length > 0 && (
                <div className="tests-section">
                    <button
                        className="tests-toggle"
                        onClick={() => setTestsOpen(!testsOpen)}
                        aria-expanded={testsOpen}
                    >
                        <span aria-hidden="true">{testsOpen ? '▼' : '▶'}</span>
                        <span>🌿 Тестовые данные</span>
                    </button>

                    {testsOpen && (
                        <>
                        <div className="lesson-block__note">
                            Отметьте тест, чтобы подставить его входные данные в «Тестовый ввод».
                        </div>
                        <div className="tests-table-wrap">
                            <table className="tests-table">
                                <thead>
                                    <tr>
                                        <th className="tests-table__check"></th>
                                        <th>№</th>
                                        <th>Входные данные</th>
                                        <th>Выходные данные</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {content.tests.map((test, index) => (
                                        <tr
                                            key={index}
                                            className={selectedTestIndex === index ? 'tests-table__row--selected' : undefined}
                                        >
                                            <td className="tests-table__check">
                                                <input
                                                    type="checkbox"
                                                    aria-label={`Подставить тест ${index + 1} во ввод`}
                                                    checked={selectedTestIndex === index}
                                                    onChange={() => handleTestCheck(index)}
                                                />
                                            </td>
                                            <td>{index + 1}</td>
                                            <td className="tests-table__io">{typeof test === 'object' ? test.input : test}</td>
                                            <td className="tests-table__io">{typeof test === 'object' ? test.expected : '—'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        </>
                    )}
                </div>
            )}

            {/* Code editor */}
            <div className="code-editor-bar">
                <span className="lesson-block__label">Ваш код:</span>
                <div ref={versionRef} className="version-select">
                    <button
                        type="button"
                        className="version-select__btn"
                        onClick={() => setVersionOpen(!versionOpen)}
                    >
                        <span>{pythonVersion}</span>
                        <span className="version-select__caret" aria-hidden="true">▼</span>
                    </button>
                    {versionOpen && (
                        <div className="version-select__menu">
                            {PYTHON_VERSIONS.map(v => (
                                <div
                                    key={v}
                                    className={v === pythonVersion
                                        ? 'version-select__item version-select__item--active'
                                        : 'version-select__item'}
                                    onClick={() => {
                                        setPythonVersion(v);
                                        setVersionOpen(false);
                                    }}
                                >
                                    {v}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
            <div className="code-editor">
                <CodeMirror
                    value={userCode}
                    onChange={(value) => setUserCode(value)}
                    extensions={[python(), pycharmDarcula]}
                    theme="none"
                    basicSetup={{
                        lineNumbers: true,
                        highlightActiveLine: true,
                        highlightActiveLineGutter: true,
                        foldGutter: false,
                        autocompletion: false,
                        indentOnInput: true,
                        bracketMatching: true,
                        closeBrackets: true,
                        tabSize: 4,
                    }}
                    indentWithTab={true}
                    minHeight="120px"
                />
            </div>

            {/* Test input box */}
            <div className="lesson-block__label">Тестовый ввод:</div>
            <textarea
                className="input code-input"
                aria-label="Тестовый ввод"
                value={testInput}
                onChange={e => setTestInput(e.target.value)}
                placeholder="Введите входные данные для проверки..."
                spellCheck={false}
            />

            {/* Run output */}
            {runOutput && (
                <div className={runOutput.stderr ? 'run-output run-output--error' : 'run-output'}>
                    <div className="run-output__label">Вывод:</div>
                    <pre className="run-output__text">
                        {runOutput.stderr || runOutput.stdout || '(нет вывода)'}
                    </pre>
                </div>
            )}

            {/* Buttons row: wraps on narrow screens */}
            <div className="code-actions">
                <div className="code-actions__main">
                    <button className="btn btn-primary" onClick={handleSubmit} disabled={isSubmitting}>
                        {isSubmitting ? '⏳ Проверяется...' : '✔ Отправить'}
                    </button>

                    {hasSubmitted && (
                        <button className="btn btn-secondary" onClick={handleReset}>
                            🔄 Сбросить
                        </button>
                    )}
                </div>

                <button className="btn btn-secondary" onClick={handleRun} disabled={isRunning}>
                    {isRunning ? '⏳ Выполняется...' : '▶ Запустить код'}
                </button>
            </div>

            {/* Submit results - success */}
            {submitResults && submitResults.status === 'success' && (
                <div className="verdict verdict--success verdict--block" role="status">
                    <div className="verdict__title">✅ Верно!</div>
                    <div className="verdict__line">
                        Все тесты пройдены ({submitResults.total}/{submitResults.total})
                    </div>
                </div>
            )}

            {/* Submit results - wrong answer */}
            {submitResults && submitResults.status === 'wrong_answer' && (
                <div className="test-fail" role="status">
                    <div className="test-fail__head">
                        ❌ Неверный ответ на {submitResults.hidden ? 'скрытом ' : ''}тесте #{submitResults.test_number}
                        <span className="test-fail__count">
                            ({submitResults.passed}/{submitResults.total} пройдено)
                        </span>
                    </div>
                    {/* Hidden tests: the server sends no input/expected/actual. */}
                    {!submitResults.hidden && (
                    <div className="test-fail__body">
                        <div className="io-box">
                            <div className="io-box__label">Входные данные</div>
                            <pre className="io-box__pre">{submitResults.input || '—'}</pre>
                        </div>
                        <div className="io-box">
                            <div className="io-box__label">Ожидаемый результат</div>
                            <pre className="io-box__pre">{submitResults.expected}</pre>
                        </div>
                        <div className="io-box">
                            <div className="io-box__label">Ваш результат</div>
                            <pre className="io-box__pre io-box__pre--actual">{submitResults.actual || '(пусто)'}</pre>
                        </div>
                    </div>
                    )}
                </div>
            )}

            {/* Submit results - error */}
            {submitResults && submitResults.status === 'error' && (
                <div className="test-fail" role="status">
                    <div className="test-fail__head">
                        {submitResults.hidden
                            ? `❌ Ошибка выполнения на скрытом тесте #${submitResults.test_number}`
                            : '❌ Ошибка выполнения'}
                    </div>
                    {/* Hidden tests: the server sends no stderr (it could reveal the input). */}
                    {!submitResults.hidden && (
                    <pre className="test-fail__stderr">{submitResults.stderr}</pre>
                    )}
                </div>
            )}

            {hiddenTestCount > 0 && (
                <div className="lesson-block__note">
                    {hasTests ? 'Ещё скрытых тестов' : 'Скрытых тестов'}: {hiddenTestCount}. Решение проверяется на всех тестах.
                </div>
            )}
        </div>
    );
}

export default CodeBlock;