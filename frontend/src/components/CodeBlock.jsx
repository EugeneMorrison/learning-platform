import { useState, useEffect, useRef } from 'react';
import api from '../api';

const PYTHON_VERSIONS = ['Python 3.10', 'Python 3.12'];

function CodeBlock({ content }) {
    const [userCode, setUserCode] = useState(content.starter_code);
    const [testsOpen, setTestsOpen] = useState(false);
    const [testInput, setTestInput] = useState('');
    const [selectedTestIndex, setSelectedTestIndex] = useState(null);
    const [runOutput, setRunOutput] = useState(null);
    const [submitResults, setSubmitResults] = useState(null);
    const [isRunning, setIsRunning] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [hasSubmitted, setHasSubmitted] = useState(false);
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
                code: userCode,
                stdin: testInput,
                version: pythonVersion,
            });
            setRunOutput(res.data);
        } catch (err) {
            setRunOutput({
                stdout: '',
                stderr: err.response?.data?.error || err.message || 'Ошибка соединения',
            });
        } finally {
            setIsRunning(false);
        }
    };

    // "Отправить" — runs against all test cases
    const handleSubmit = async () => {
        setIsSubmitting(true);
        setSubmitResults(null);
        setHasSubmitted(true);
        try {
            const res = await api.post('/run-tests/', {
                code: userCode,
                tests: content.tests,
                version: pythonVersion,
            });
            setSubmitResults(res.data);
        } catch (err) {
            setSubmitResults({
                status: 'error',
                stderr: err.response?.data?.error || err.message || 'Ошибка соединения',
            });
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleReset = () => {
        setUserCode(content.starter_code);
        setTestInput('');
        setSelectedTestIndex(null);
        setRunOutput(null);
        setSubmitResults(null);
        setHasSubmitted(false);
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Tab') {
            e.preventDefault();
            const { selectionStart, selectionEnd } = e.target;
            const newCode =
                userCode.substring(0, selectionStart) +
                '    ' +
                userCode.substring(selectionEnd);
            setUserCode(newCode);
            setTimeout(() => {
                e.target.selectionStart = e.target.selectionEnd = selectionStart + 4;
            }, 0);
        }
    };

    return (
        <div style={{
            background: 'white',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            borderLeft: '4px solid #16a34a',
        }}>
            {/* Block type badge */}
            <div style={{ marginBottom: '14px' }}>
                <span style={{
                    display: 'inline-block',
                    padding: '4px 12px',
                    background: '#dcfce7',
                    color: '#15803d',
                    borderRadius: '999px',
                    fontWeight: '600',
                    letterSpacing: '0.3px',
                }}>
                    Задача
                </span>
            </div>

            {/* Task prompt */}
            <div
                style={{ marginBottom: '16px' }}
                dangerouslySetInnerHTML={{ __html: content.prompt }}
            />

            {/* Code editor */}
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '8px',
                fontSize: '14px',
            }}>
                <span style={{ color: '#64748b' }}>Ваш код:</span>
                <div ref={versionRef} style={{ position: 'relative' }}>
                    <button
                        type="button"
                        onClick={() => setVersionOpen(!versionOpen)}
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '6px 12px',
                            background: 'white',
                            color: '#334155',
                            border: '1px solid #cbd5e1',
                            borderRadius: '6px',
                            fontSize: '13px',
                            fontWeight: '500',
                            cursor: 'pointer',
                            minWidth: '130px',
                            justifyContent: 'space-between',
                        }}
                    >
                        <span>{pythonVersion}</span>
                        <span style={{ fontSize: '10px', color: '#64748b' }}>▼</span>
                    </button>
                    {versionOpen && (
                        <div style={{
                            position: 'absolute',
                            top: 'calc(100% + 4px)',
                            right: 0,
                            minWidth: '140px',
                            background: 'white',
                            border: '1px solid #e2e8f0',
                            borderRadius: '6px',
                            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
                            zIndex: 10,
                            overflow: 'hidden',
                        }}>
                            {PYTHON_VERSIONS.map(v => (
                                <div
                                    key={v}
                                    onClick={() => {
                                        setPythonVersion(v);
                                        setVersionOpen(false);
                                    }}
                                    style={{
                                        padding: '8px 12px',
                                        cursor: 'pointer',
                                        fontSize: '13px',
                                        background: v === pythonVersion ? '#dcfce7' : 'white',
                                        color: '#334155',
                                    }}
                                    onMouseEnter={e => {
                                        if (v !== pythonVersion) e.currentTarget.style.background = '#f8fafc';
                                    }}
                                    onMouseLeave={e => {
                                        if (v !== pythonVersion) e.currentTarget.style.background = 'white';
                                    }}
                                >
                                    {v}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
            <textarea
                value={userCode}
                onChange={e => setUserCode(e.target.value)}
                onKeyDown={handleKeyDown}
                spellCheck={false}
                style={{
                    width: '100%',
                    background: '#1e293b',
                    color: '#e2e8f0',
                    fontFamily: "'JetBrains Mono', Consolas, monospace",
                    fontSize: '14px',
                    padding: '16px',
                    borderRadius: '6px',
                    border: 'none',
                    resize: 'vertical',
                    minHeight: '120px',
                    marginBottom: '16px',
                    boxSizing: 'border-box',
                    outline: 'none',
                    lineHeight: '1.6',
                    tabSize: 4,
                }}
            />

            {/* Test input box */}
            <div style={{ marginBottom: '8px', color: '#64748b', fontSize: '14px' }}>
                Тестовый ввод:
            </div>
            <textarea
                value={testInput}
                onChange={e => setTestInput(e.target.value)}
                placeholder="Введите входные данные для проверки..."
                spellCheck={false}
                style={{
                    width: '100%',
                    background: '#f8fafc',
                    color: '#334155',
                    fontFamily: "'JetBrains Mono', Consolas, monospace",
                    fontSize: '14px',
                    padding: '12px 16px',
                    borderRadius: '6px',
                    border: '1px solid #e2e8f0',
                    resize: 'vertical',
                    minHeight: '72px',
                    marginBottom: '12px',
                    boxSizing: 'border-box',
                    outline: 'none',
                    lineHeight: '1.6',
                }}
            />

            {/* Run output */}
            {runOutput && (
                <div style={{
                    marginBottom: '16px',
                    background: '#1e293b',
                    borderRadius: '6px',
                    overflow: 'hidden',
                }}>
                    <div style={{
                        padding: '8px 16px',
                        background: '#0f172a',
                        color: '#64748b',
                        fontSize: '12px',
                        fontWeight: '600',
                    }}>
                        Вывод:
                    </div>
                    <pre style={{
                        margin: 0,
                        padding: '12px 16px',
                        color: runOutput.stderr ? '#dc2626' : '#0f172a',
                        fontFamily: "'JetBrains Mono', Consolas, monospace",
                        fontSize: '13px',
                        lineHeight: '1.5',
                        whiteSpace: 'pre-wrap',
                    }}>
                        {runOutput.stderr || runOutput.stdout || '(нет вывода)'}
                    </pre>
                </div>
            )}

            {/* Buttons row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
                <div style={{ display: 'flex', gap: '12px' }}>
                    <button
                        onClick={handleSubmit}
                        disabled={isSubmitting}
                        style={{
                            padding: '10px 24px',
                            background: isSubmitting ? '#93c5fd' : '#2563eb',
                            color: 'white',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: isSubmitting ? 'not-allowed' : 'pointer',
                            fontWeight: '600',
                            fontSize: '14px',
                        }}
                    >
                        {isSubmitting ? '⏳ Проверяется...' : '✔ Отправить'}
                    </button>

                    {hasSubmitted && (
                        <button
                            onClick={handleReset}
                            style={{
                                padding: '10px 24px',
                                background: 'white',
                                color: '#64748b',
                                border: '1px solid #e2e8f0',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                fontWeight: '600',
                                fontSize: '14px',
                            }}
                        >
                            🔄 Сбросить
                        </button>
                    )}
                </div>

                <button
                    onClick={handleRun}
                    disabled={isRunning}
                    style={{
                        padding: '10px 24px',
                        background: isRunning ? '#86efac' : '#1e293b',
                        color: 'white',
                        border: 'none',
                        borderRadius: '6px',
                        cursor: isRunning ? 'not-allowed' : 'pointer',
                        fontWeight: '600',
                        fontSize: '14px',
                    }}
                >
                    {isRunning ? '⏳ Выполняется...' : '▶ Запустить код'}
                </button>
            </div>

            {/* Submit results - success */}
            {submitResults && submitResults.status === 'success' && (
                <div style={{
                    padding: '16px',
                    background: '#f0fdf4',
                    border: '1px solid #bbf7d0',
                    borderRadius: '8px',
                    marginBottom: '16px',
                }}>
                    <div style={{ fontSize: '18px', fontWeight: '700', color: '#16a34a', marginBottom: '4px' }}>
                        Верно!
                    </div>
                    <div style={{ color: '#15803d', fontSize: '14px' }}>
                        Все тесты пройдены ({submitResults.total}/{submitResults.total})
                    </div>
                </div>
            )}

            {/* Submit results - wrong answer */}
            {submitResults && submitResults.status === 'wrong_answer' && (
                <div style={{
                    marginBottom: '16px',
                    border: '1px solid #fecaca',
                    borderRadius: '8px',
                    overflow: 'hidden',
                }}>
                    <div style={{
                        padding: '12px 16px',
                        background: '#fef2f2',
                        fontWeight: '700',
                        fontSize: '15px',
                        color: '#dc2626',
                    }}>
                        Неверный ответ на тесте #{submitResults.test_number}
                        <span style={{ fontWeight: '400', fontSize: '13px', marginLeft: '12px', color: '#64748b' }}>
                            ({submitResults.passed}/{submitResults.total} пройдено)
                        </span>
                    </div>
                    <div style={{ padding: '14px 16px', background: 'white' }}>
                        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                            <div style={{ flex: 1, minWidth: '150px' }}>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: '#94a3b8', marginBottom: '4px', textTransform: 'uppercase' }}>
                                    Входные данные
                                </div>
                                <pre style={preBoxStyle}>{submitResults.input || '—'}</pre>
                            </div>
                            <div style={{ flex: 1, minWidth: '150px' }}>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: '#94a3b8', marginBottom: '4px', textTransform: 'uppercase' }}>
                                    Ожидаемый результат
                                </div>
                                <pre style={{ ...preBoxStyle, borderColor: '#bbf7d0', background: '#f0fdf4' }}>
                                    {submitResults.expected}
                                </pre>
                            </div>
                            <div style={{ flex: 1, minWidth: '150px' }}>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: '#94a3b8', marginBottom: '4px', textTransform: 'uppercase' }}>
                                    Ваш результат
                                </div>
                                <pre style={{ ...preBoxStyle, borderColor: '#fecaca', background: '#fef2f2' }}>
                                    {submitResults.actual || '(пусто)'}
                                </pre>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Submit results - error */}
            {submitResults && submitResults.status === 'error' && (
                <div style={{
                    marginBottom: '16px',
                    border: '1px solid #fecaca',
                    borderRadius: '8px',
                    overflow: 'hidden',
                }}>
                    <div style={{
                        padding: '12px 16px',
                        background: '#fef2f2',
                        fontWeight: '700',
                        fontSize: '15px',
                        color: '#dc2626',
                    }}>
                        Ошибка выполнения
                    </div>
                    <pre style={{
                        margin: 0,
                        padding: '14px 16px',
                        background: '#1e1e1e',
                        color: '#f87171',
                        fontFamily: "'JetBrains Mono', Consolas, monospace",
                        fontSize: '13px',
                        lineHeight: '1.5',
                        whiteSpace: 'pre-wrap',
                    }}>
                        {submitResults.stderr}
                    </pre>
                </div>
            )}

            {/* Collapsible tests table */}
            {content.tests && content.tests.length > 0 && (
                <div style={{ marginTop: '8px' }}>
                    <button
                        onClick={() => setTestsOpen(!testsOpen)}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            fontSize: '14px',
                            fontWeight: '600',
                            color: '#475569',
                            padding: '0',
                        }}
                    >
                        <span>{testsOpen ? '▼' : '▶'}</span>
                        <span>🌿 Тестовые данные</span>
                    </button>

                    {testsOpen && (
                        <div style={{ marginTop: '12px', overflowX: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                                <thead>
                                    <tr style={{ background: '#f1f5f9' }}>
                                        <th style={{ ...thStyle, width: '36px', textAlign: 'center' }}></th>
                                        <th style={thStyle}>№</th>
                                        <th style={thStyle}>Входные данные</th>
                                        <th style={thStyle}>Выходные данные</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {content.tests.map((test, index) => (
                                        <tr key={index} style={{
                                            background: index % 2 === 0 ? 'white' : '#f8fafc'
                                        }}>
                                            <td style={{ ...tdStyle, textAlign: 'center' }}>
                                                <input
                                                    type="checkbox"
                                                    checked={selectedTestIndex === index}
                                                    onChange={() => handleTestCheck(index)}
                                                    style={{ cursor: 'pointer' }}
                                                />
                                            </td>
                                            <td style={tdStyle}>{index + 1}</td>
                                            <td style={tdStyle}>
                                                {typeof test === 'object' ? test.input : test}
                                            </td>
                                            <td style={{ ...tdStyle, color: '#16a34a', fontWeight: '600' }}>
                                                {typeof test === 'object' ? test.expected : '—'}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

const preBoxStyle = {
    margin: 0,
    padding: '10px 14px',
    background: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: '6px',
    fontFamily: "'JetBrains Mono', Consolas, monospace",
    fontSize: '13px',
    lineHeight: '1.5',
    whiteSpace: 'pre-wrap',
};

const thStyle = {
    padding: '10px 16px',
    textAlign: 'left',
    fontWeight: '600',
    color: '#475569',
    border: '1px solid #e2e8f0',
};

const tdStyle = {
    padding: '8px 16px',
    border: '1px solid #e2e8f0',
    fontFamily: "'JetBrains Mono', Consolas, monospace",
};

export default CodeBlock;