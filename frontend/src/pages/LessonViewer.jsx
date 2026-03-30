import { useState, useEffect } from 'react';
import { login, getLesson, getBlocks } from '../api';
import TextBlock from '../components/TextBlock';
import QuizBlock from '../components/QuizBlock';
import CodeBlock from '../components/CodeBlock';

// Extract lesson ID from URL: /lesson/<uuid>/
// Django serves this page at /lesson/<uuid>/, React reads it from the path
// Falls back to hardcoded ID during Vite dev mode (localhost:5173/)
const DEV_LESSON_ID = '6f1c0c31-7be5-4434-ac25-c00f8031d15c';

function getLessonIdFromUrl() {
    const parts = window.location.pathname.split('/');
    // URL looks like: /lesson/6f1c0c31-7be5-4434-ac25-c00f8031d15c/
    // parts = ['', 'lesson', '6f1c0c31-...', '']
    const idx = parts.indexOf('lesson');
    if (idx !== -1 && parts[idx + 1]) return parts[idx + 1];
    // Fallback for Vite dev server (no /lesson/ in path)
    return import.meta.env.DEV ? DEV_LESSON_ID : null;
}

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
            const lessonId = getLessonIdFromUrl();
            if (!lessonId) {
                setError('Lesson ID not found in URL. Open /lesson/<uuid>/');
                setLoading(false);
                return;
            }

            // Step 1: login as alice (student) to get JWT token
            // Login response format: { user: {...}, tokens: { access: "...", refresh: "..." } }
            const loginResponse = await login('alice', 'password123');
            const token = loginResponse.data.tokens.access;
            localStorage.setItem('access_token', token);

            // Step 2: fetch lesson info and blocks in parallel
            const [lessonResponse, blocksResponse] = await Promise.all([
                getLesson(lessonId),
                getBlocks(lessonId),
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
                    Урок {lesson.order_index}
                </div>
                <h1 style={{ fontSize: '28px', color: '#0C4B33' }}>
                    {lesson.title}
                </h1>
                <div style={{ marginTop: '12px', color: '#64748b', fontSize: '14px' }}>
                    {blocks.length} блоков
                </div>
            </div>

            {/* Render all blocks */}
            {blocks.map(renderBlock)}

        </div>
    );
}

export default LessonViewer;