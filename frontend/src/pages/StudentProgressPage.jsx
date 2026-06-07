import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { pycharmDarcula } from '../components/pycharmDarcula';
import api from '../api';
import UserBadge from '../components/UserBadge';

function StudentProgressPage() {
    const { courseId, studentId } = useParams();
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [openBlocks, setOpenBlocks] = useState(() => new Set());
    const [openAttempts, setOpenAttempts] = useState(() => new Set());

    function toggleBlock(blockId) {
        setOpenBlocks(prev => {
            const next = new Set(prev);
            if (next.has(blockId)) next.delete(blockId); else next.add(blockId);
            return next;
        });
    }

    function toggleAttempt(attemptId) {
        setOpenAttempts(prev => {
            const next = new Set(prev);
            if (next.has(attemptId)) next.delete(attemptId); else next.add(attemptId);
            return next;
        });
    }

    function formatDateTime(iso) {
        return new Date(iso).toLocaleString('ru-RU', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit', second: '2-digit',
        });
    }

    function renderAnswerBody(answer, blockType) {
        if (!answer) return <em style={{ color: '#94a3b8' }}>пусто</em>;
        if (blockType === 'CODE') {
            const code = typeof answer.code === 'string'
                ? answer.code
                : JSON.stringify(answer, null, 2);
            return (
                <div style={{
                    borderRadius: '6px',
                    overflow: 'hidden',
                }}>
                    <CodeMirror
                        value={code}
                        extensions={[python(), pycharmDarcula]}
                        theme="none"
                        editable={false}
                        basicSetup={{
                            lineNumbers: true,
                            highlightActiveLine: false,
                            highlightActiveLineGutter: false,
                            foldGutter: false,
                            autocompletion: false,
                            indentOnInput: false,
                            bracketMatching: false,
                            closeBrackets: false,
                        }}
                    />
                </div>
            );
        }
        if (blockType === 'QUIZ') {
            const selected = answer.selected;
            return (
                <div style={{
                    padding: '10px 14px',
                    background: '#f8fafc',
                    border: '1px solid #e2e8f0',
                    borderRadius: '6px',
                    fontSize: '13px',
                }}>
                    Выбран вариант <strong>{(typeof selected === 'number' ? selected + 1 : '?')}</strong>
                </div>
            );
        }
        return (
            <pre style={{ margin: 0, fontSize: '13px' }}>{JSON.stringify(answer, null, 2)}</pre>
        );
    }

    useEffect(() => {
        async function fetchProgress() {
            try {
                const response = await api.get(
                    `/progress/student/${studentId}/course/${courseId}/`
                );
                setData(response.data);
            } catch (err) {
                console.error('Failed to load progress:', err);
            } finally {
                setLoading(false);
            }
        }
        fetchProgress();
    }, [studentId, courseId]);

    if (loading) return <p>Загрузка...</p>;
    if (!data) return <p>Данные не найдены.</p>;

    // Theory (TEXT) blocks aren't tasks — there's nothing to solve — so the
    // "Заданий" stats count only QUIZ/CODE blocks. This also lets the bar reach
    // 100% (TEXT blocks never get a Progress record and would otherwise drag it).
    const taskBlocks = data.lessons.flatMap(l => l.blocks.filter(b => b.block_type !== 'TEXT'));
    const totalTasks = taskBlocks.length;
    const completedTasks = taskBlocks.filter(b => b.completed).length;
    const taskPercentage = totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0;

    return (
        <div style={{ maxWidth: '800px', margin: '40px auto', padding: '20px' }}>
            <UserBadge />

            {/* Header */}
            <button onClick={() => navigate(`/courses/${courseId}/`)} style={{ marginBottom: '20px' }}>
                ← Назад
            </button>
            <h2>Прогресс студента: {data.student_username}</h2>
            <p style={{ color: '#64748b' }}>Курс: {data.course_title}</p>

            {/* Summary */}
            <div style={{
                background: '#f8fafc',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                padding: '16px',
                marginTop: '16px',
                display: 'flex',
                gap: '32px',
            }}>
                <div>
                    <div style={{ fontSize: '28px', fontWeight: 'bold', color: '#0C4B33' }}>
                        {taskPercentage}%
                    </div>
                    <div style={{ color: '#64748b', fontSize: '14px' }}>Выполнено</div>
                </div>
                <div>
                    <div style={{ fontSize: '28px', fontWeight: 'bold' }}>
                        {completedTasks}/{totalTasks}
                    </div>
                    <div style={{ color: '#64748b', fontSize: '14px' }}>Заданий</div>
                </div>
                <div>
                    <div style={{ fontSize: '28px', fontWeight: 'bold' }}>
                        {data.correct_answers}/{data.total_quizzes}
                    </div>
                    <div style={{ color: '#64748b', fontSize: '14px' }}>Тестов верно</div>
                </div>
            </div>

            {/* Lessons breakdown */}
            <div style={{ marginTop: '24px' }}>
                {data.lessons.map((lesson, idx) => {
                    // Theory (TEXT) blocks aren't tasks — skip them entirely.
                    const lessonTasks = lesson.blocks.filter(b => b.block_type !== 'TEXT');

                    // Per-type counters reset for each lesson
                    let quizCount = 0;
                    let codeCount = 0;
                    const typeLabels = lessonTasks.map(block => {
                        if (block.block_type === 'QUIZ') {
                            quizCount += 1;
                            return `Тест ${quizCount}`;
                        }
                        codeCount += 1;
                        return `Задача ${codeCount}`;
                    });

                    return (
                        <div key={idx} style={{
                            border: '1px solid #e2e8f0',
                            borderRadius: '8px',
                            padding: '16px',
                            marginTop: '12px',
                        }}>
                            <h4 style={{ margin: '0 0 12px 0' }}>
                                Урок {lesson.lesson_order}: {lesson.lesson_title}
                            </h4>
                            {lessonTasks.length === 0 && (
                                <p style={{ margin: 0, color: '#94a3b8', fontSize: '14px' }}>
                                    В этом уроке нет заданий — только теория.
                                </p>
                            )}
                            {lessonTasks.map((block, bidx) => {
                                const history = block.attempts_history || [];
                                const isOpen = openBlocks.has(block.block_id);
                                const hasHistory = history.length > 0;
                                return (
                                    <div key={bidx} style={{
                                        padding: '8px 0',
                                        borderTop: bidx > 0 ? '1px solid #f1f5f9' : 'none',
                                    }}>
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '12px',
                                        }}>
                                            <span style={{ fontSize: '20px' }}>
                                                {block.completed ? '✅' : '○'}
                                            </span>
                                            <span style={{ color: '#64748b', fontSize: '14px' }}>
                                                Задание {bidx + 1} ({typeLabels[bidx]})
                                            </span>
                                            {/* QUIZ and CODE both report is_correct, so show the
                                                verdict for either once submitted. */}
                                            {block.completed && block.is_correct != null && (
                                                <span style={{
                                                    fontSize: '13px',
                                                    color: block.is_correct ? '#16a34a' : '#dc2626',
                                                }}>
                                                    {block.is_correct ? '✓ Верно' : '✗ Неверно'}
                                                </span>
                                            )}
                                            {hasHistory && (
                                                <button
                                                    onClick={() => toggleBlock(block.block_id)}
                                                    style={{
                                                        background: 'none',
                                                        border: '1px solid #e2e8f0',
                                                        borderRadius: '999px',
                                                        padding: '2px 10px',
                                                        cursor: 'pointer',
                                                        fontSize: '12px',
                                                        color: '#475569',
                                                        fontWeight: 500,
                                                    }}
                                                    title="Показать историю попыток"
                                                >
                                                    {isOpen ? '▼' : '▶'} попыток: {history.length}
                                                </button>
                                            )}
                                            {block.completed_at && (
                                                <span style={{ fontSize: '12px', color: '#94a3b8', marginLeft: 'auto' }}>
                                                    {new Date(block.completed_at).toLocaleDateString('ru-RU')}
                                                </span>
                                            )}
                                        </div>

                                        {hasHistory && isOpen && (
                                            <div style={{
                                                marginTop: '8px',
                                                marginLeft: '32px',
                                                padding: '8px 12px',
                                                background: '#f8fafc',
                                                border: '1px solid #e2e8f0',
                                                borderRadius: '6px',
                                            }}>
                                                {history.map((attempt, idx) => {
                                                    const isAttemptOpen = openAttempts.has(attempt.id);
                                                    return (
                                                        <div key={attempt.id} style={{
                                                            padding: '6px 0',
                                                            borderTop: idx > 0 ? '1px solid #e2e8f0' : 'none',
                                                        }}>
                                                            <div
                                                                onClick={() => toggleAttempt(attempt.id)}
                                                                style={{
                                                                    display: 'flex',
                                                                    alignItems: 'center',
                                                                    gap: '10px',
                                                                    cursor: 'pointer',
                                                                    userSelect: 'none',
                                                                }}
                                                            >
                                                                <span style={{ fontSize: '12px', color: '#64748b', width: '12px' }}>
                                                                    {isAttemptOpen ? '▼' : '▶'}
                                                                </span>
                                                                <span style={{
                                                                    fontSize: '14px',
                                                                    color: attempt.is_correct ? '#16a34a' : (attempt.is_correct === false ? '#dc2626' : '#64748b'),
                                                                    width: '16px',
                                                                }}>
                                                                    {attempt.is_correct ? '✓' : (attempt.is_correct === false ? '✗' : '·')}
                                                                </span>
                                                                <span style={{ fontSize: '13px', color: '#475569' }}>
                                                                    Попытка {idx + 1}
                                                                </span>
                                                                <span style={{ fontSize: '12px', color: '#94a3b8', marginLeft: 'auto' }}>
                                                                    {formatDateTime(attempt.created_at)}
                                                                </span>
                                                            </div>
                                                            {isAttemptOpen && (
                                                                <div style={{ marginTop: '8px', marginLeft: '38px' }}>
                                                                    {renderAnswerBody(attempt.answer, block.block_type)}
                                                                </div>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export default StudentProgressPage;