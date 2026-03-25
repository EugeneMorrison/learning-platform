import { useState } from 'react';
import api from '../api';

function CodeBlock({ content }) {
    const [userCode, setUserCode] = useState(content.starter_code);
    const [results, setResults] = useState(null);
    const [isRunning, setIsRunning] = useState(false);

    const handleRun = async () => {
        setIsRunning(true);
        setResults(null);
        try {
            const res = await api.post('/run-tests/', {
                code: userCode,
                tests: content.tests,
            });
            setResults(res.data);
        } catch (err) {
            const msg = err.response?.data?.error
                || err.response?.statusText
                || err.message
                || 'Failed to connect to server';
            setResults({ status: 'error', stderr: msg });
        } finally {
            setIsRunning(false);
        }
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
            {/* Task prompt */}
            <div
                style={{ marginBottom: '16px' }}
                dangerouslySetInnerHTML={{ __html: content.prompt }}
            />

            {/* Code editor */}
            <div style={{ marginBottom: '8px', color: '#64748b', fontSize: '14px' }}>
                Ваш код:
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

            {/* Run button */}
            <button
                onClick={handleRun}
                disabled={isRunning}
                style={{
                    marginBottom: '16px',
                    padding: '10px 24px',
                    background: isRunning ? '#86efac' : '#16a34a',
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

            {/* Results */}
            {results && results.status === 'success' && (
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
                        Все тесты пройдены ({results.total}/{results.total})
                    </div>
                </div>
            )}

            {results && results.status === 'error' && (
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
                        Runtime Error
                        {results.test_number && (
                            <span style={{ fontWeight: '400', fontSize: '13px', marginLeft: '8px' }}>
                                (test #{results.test_number})
                            </span>
                        )}
                    </div>
                    {results.input && (
                        <div style={{
                            padding: '10px 16px',
                            background: '#fff5f5',
                            borderBottom: '1px solid #fecaca',
                            fontSize: '13px',
                        }}>
                            <span style={{ color: '#64748b' }}>Input: </span>
                            <span style={{ fontFamily: "'JetBrains Mono', Consolas, monospace", color: '#334155' }}>
                                {results.input}
                            </span>
                        </div>
                    )}
                    <pre style={{
                        margin: 0,
                        padding: '14px 16px',
                        background: '#1e1e1e',
                        color: '#f87171',
                        fontFamily: "'JetBrains Mono', Consolas, monospace",
                        fontSize: '13px',
                        lineHeight: '1.5',
                        whiteSpace: 'pre-wrap',
                        overflowX: 'auto',
                    }}>
                        {results.stderr}
                    </pre>
                </div>
            )}

            {results && results.status === 'wrong_answer' && (
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
                        Неверный ответ на тесте #{results.test_number}
                        <span style={{ fontWeight: '400', fontSize: '13px', marginLeft: '12px', color: '#64748b' }}>
                            ({results.passed}/{results.total} passed)
                        </span>
                    </div>
                    <div style={{ padding: '14px 16px', background: 'white' }}>
                        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
                            <div style={{ flex: 1, minWidth: '150px' }}>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: '#94a3b8', marginBottom: '4px', textTransform: 'uppercase' }}>
                                    Входные данные
                                </div>
                                <pre style={preBoxStyle}>{results.input || '—'}</pre>
                            </div>
                            <div style={{ flex: 1, minWidth: '150px' }}>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: '#94a3b8', marginBottom: '4px', textTransform: 'uppercase' }}>
                                    Ожидаемый результат
                                </div>
                                <pre style={{ ...preBoxStyle, borderColor: '#bbf7d0', background: '#f0fdf4' }}>
                                    {results.expected}
                                </pre>
                            </div>
                            <div style={{ flex: 1, minWidth: '150px' }}>
                                <div style={{ fontSize: '12px', fontWeight: '600', color: '#94a3b8', marginBottom: '4px', textTransform: 'uppercase' }}>
                                    Ваш результат
                                </div>
                                <pre style={{ ...preBoxStyle, borderColor: '#fecaca', background: '#fef2f2' }}>
                                    {results.actual || '(empty)'}
                                </pre>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Test case count hint */}
            {!results && content.tests && content.tests.length > 0 && (
                <div style={{ color: '#94a3b8', fontSize: '13px' }}>
                    {content.tests.length} test case{content.tests.length > 1 ? 's' : ''} тестов скрыто
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

export default CodeBlock;
