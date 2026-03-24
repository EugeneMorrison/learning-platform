import { useState, useEffect } from 'react';
import { login, getLesson, getBlocks } from '../api';
import TextBlock from '../components/TextBlock';
import QuizBlock from '../components/QuizBlock';
import CodeBlock from '../components/CodeBlock';

// --- CHANGE THIS to the lesson ID you want to display ---
// Get the ID from Django admin or browsable API:
// http://127.0.0.1:9000/api/lessons/ - cope lesson id from here
const LESSON_ID = '6f1c0c31-7be5-4434-ac25-c00f8031d15c';

function LessonViewer() {
    const [lesson, setLesson] = useState(null);
    const [blocks, setBlocks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        loadLesson();
    }, []);

    async function loadLesson() {
        try {
            // Step 1: login as alice (student) to get JWT token
            const loginResponse = await login('alice', 'password123');
            const token = loginResponse.data.access;
            localStorage.setItem('access_token', token);

            // Step 2: fetch lesson info and blocks in parallel
            const [lessonResponse, blocksResponse] = await Promise.all([
                getLesson(LESSON_ID),
                getBlocks(LESSON_ID),
            ]);

            setLesson(lessonResponse.data);
            setBlocks(blocksResponse.data);
        } catch (err) {
            setError('Failed to load lesson. Check console for details.');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }

    function renderBlock(block) {
        switch (block.type) {
            case 'TEXT':
                return <TextBlock key={block.id} content={block.content} />;
            case 'QUIZ':
                return <QuizBlock key={block.id} content={block.content} />;
            case 'CODE':
                return <CodeBlock key={block.id} content={block.content} />;
            default:
                return null;
        }
    }

    if (loading) return (
        <div style={{ padding: '40px', textAlign: 'center', color: '#64748b' }}>
            Loading lesson...
        </div>
    );

    if (error) return (
        <div style={{ padding: '40px', textAlign: 'center', color: '#dc2626' }}>
            {error}
        </div>
    );

    return (
        <div style={{ maxWidth: '800px', margin: '0 auto', padding: '40px 20px' }}>

            {/* Lesson header */}
            <div style={{
                background: 'white',
                borderRadius: '8px',
                padding: '32px',
                marginBottom: '24px',
                boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
                borderTop: '4px solid #0C4B33',
            }}>
                <div style={{ fontSize: '14px', color: '#64748b', marginBottom: '8px' }}>
                    Lesson {lesson.order_index}
                </div>
                <h1 style={{ fontSize: '28px', color: '#0C4B33' }}>
                    {lesson.title}
                </h1>
                <div style={{ marginTop: '12px', color: '#64748b', fontSize: '14px' }}>
                    {blocks.length} blocks
                </div>
            </div>

            {/* Render all blocks */}
            {blocks.map(renderBlock)}

        </div>
    );
}

export default LessonViewer;