import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api';

function StudentProgressPage() {
    const { courseId, studentId } = useParams();
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

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

    return (
        <div style={{ maxWidth: '800px', margin: '40px auto', padding: '20px' }}>

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
                        {data.progress_percentage}%
                    </div>
                    <div style={{ color: '#64748b', fontSize: '14px' }}>Выполнено</div>
                </div>
                <div>
                    <div style={{ fontSize: '28px', fontWeight: 'bold' }}>
                        {data.completed_blocks}/{data.total_blocks}
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
                {data.lessons.map((lesson, idx) => (
                    <div key={idx} style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: '8px',
                        padding: '16px',
                        marginTop: '12px',
                    }}>
                        <h4 style={{ margin: '0 0 12px 0' }}>
                            Урок {lesson.lesson_order}: {lesson.lesson_title}
                        </h4>
                        {lesson.blocks.map((block, bidx) => (
                            <div key={bidx} style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '12px',
                                padding: '8px 0',
                                borderTop: bidx > 0 ? '1px solid #f1f5f9' : 'none',
                            }}>
                                <span style={{ fontSize: '20px' }}>
                                    {block.completed ? '✅' : '○'}
                                </span>
                                <span style={{ color: '#64748b', fontSize: '14px' }}>
                                    Блок {block.block_order} — {block.block_type}
                                </span>
                                {block.block_type === 'QUIZ' && block.completed && (
                                    <span style={{
                                        fontSize: '13px',
                                        color: block.is_correct ? '#16a34a' : '#dc2626',
                                    }}>
                                        {block.is_correct ? '✓ Верно' : '✗ Неверно'}
                                    </span>
                                )}
                                {block.completed_at && (
                                    <span style={{ fontSize: '12px', color: '#94a3b8', marginLeft: 'auto' }}>
                                        {new Date(block.completed_at).toLocaleDateString('ru-RU')}
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                ))}
            </div>
        </div>
    );
}

export default StudentProgressPage;