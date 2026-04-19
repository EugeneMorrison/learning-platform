import { useState, useEffect } from 'react';
import { getLesson, getBlocks } from '../api';
import api from '../api';
import TextBlock from '../components/TextBlock';
import QuizBlock from '../components/QuizBlock';
import CodeBlock from '../components/CodeBlock';

const DEV_LESSON_ID = '6f1c0c31-7be5-4434-ac25-c00f8031d15c';

function getLessonIdFromUrl() {
    const parts = window.location.pathname.split('/');
    const idx = parts.indexOf('lesson');
    if (idx !== -1 && parts[idx + 1]) return parts[idx + 1];
    return import.meta.env.DEV ? DEV_LESSON_ID : null;
}

function LessonViewer() {
    const [lesson, setLesson] = useState(null);
    const [blocks, setBlocks] = useState([]);
    const [course, setCourse] = useState(null);
    const [progress, setProgress] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showChat, setShowChat] = useState(false);
    const [messages, setMessages] = useState([]);
    const [newMessage, setNewMessage] = useState('');
    const [sendingMessage, setSendingMessage] = useState(false);

    const solvedBlockIds = new Set(
        progress.filter(p => p.is_correct === true).map(p => p.block)
    );
    const firstUnresolved = blocks.find(
        b => (b.type === 'QUIZ' || b.type === 'CODE') && !solvedBlockIds.has(b.id)
    );

    function scrollToNextTask() {
        if (!firstUnresolved) return;
        const el = document.getElementById(`block-${firstUnresolved.id}`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    useEffect(() => {
        loadLesson();
    }, []);

    async function loadLesson() {
        try {
            const lessonId = getLessonIdFromUrl();
            if (!lessonId) {
                setError('Lesson ID not found in URL.');
                setLoading(false);
                return;
            }
            const [lessonResponse, blocksResponse] = await Promise.all([
                getLesson(lessonId),
                getBlocks(lessonId),
            ]);
            setLesson(lessonResponse.data);
            setBlocks(blocksResponse.data);
            const courseResponse = await api.get(`/courses/${lessonResponse.data.course}/`);
            setCourse(courseResponse.data);
            const progressResponse = await api.get(`/progress/course/${lessonResponse.data.course}/`);
            setProgress(progressResponse.data);
        } catch (err) {
            setError('Failed to load lesson. Check console for details.');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }

    async function fetchMessages() {
        if (!course) return;
        try {
            const res = await api.get(`/messages/?course=${course.id}`);
            setMessages(res.data);
        } catch (err) {
            console.error('Failed to load messages:', err);
        }
    }

    async function handleSendMessage(e) {
        e.preventDefault();
        if (!newMessage.trim() || !course) return;
        setSendingMessage(true);
        try {
            await api.post('/messages/', {
                course: course.id,
                receiver: course.author,
                text: newMessage,
            });
            setNewMessage('');
            await fetchMessages();
        } catch (err) {
            console.error('Failed to send message:', err);
        } finally {
            setSendingMessage(false);
        }
    }

    function handleOpenChat() {
        setShowChat(!showChat);
        if (!showChat) fetchMessages();
    }

    function renderBlock(block) {
        let inner = null;
        switch (block.type) {
            case 'TEXT':
                inner = <TextBlock blockId={block.id} content={block.content} />;
                break;
            case 'QUIZ':
                inner = <QuizBlock blockId={block.id} content={block.content} />;
                break;
            case 'CODE':
                inner = <CodeBlock blockId={block.id} content={block.content} />;
                break;
            default:
                return null;
        }
        return <div key={block.id} id={`block-${block.id}`}>{inner}</div>;
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
        <>
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

            {/* Floating "next task" button */}
            {firstUnresolved && (
                <button
                    onClick={scrollToNextTask}
                    style={{
                        position: 'fixed',
                        bottom: '24px',
                        left: '24px',
                        zIndex: 1000,
                        padding: '12px 20px',
                        background: '#0C4B33',
                        color: 'white',
                        border: 'none',
                        borderRadius: '24px',
                        fontSize: '14px',
                        fontWeight: '600',
                        cursor: 'pointer',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
                    }}
                >
                    К следующей задаче ↓
                </button>
            )}

            {/* Floating chat button */}
            <div style={{ position: 'fixed', bottom: '24px', right: '24px', zIndex: 1000 }}>

                {showChat && (
                    <div style={{
                        width: '320px',
                        background: 'white',
                        borderRadius: '12px',
                        boxShadow: '0 4px 24px rgba(0,0,0,0.15)',
                        marginBottom: '12px',
                        overflow: 'hidden',
                    }}>
                        <div style={{
                            background: '#0C4B33',
                            color: 'white',
                            padding: '12px 16px',
                            fontWeight: '600',
                        }}>
                            💬 Чат с учителем
                        </div>
                        <div style={{
                            height: '250px',
                            overflowY: 'auto',
                            padding: '12px',
                            background: '#f8fafc',
                        }}>
                            {messages.length === 0 ? (
                                <p style={{ color: '#94a3b8', textAlign: 'center', fontSize: '14px' }}>
                                    Сообщений пока нет
                                </p>
                            ) : (
                                messages.map(msg => (
                                    <div key={msg.id} style={{
                                        marginBottom: '8px',
                                        textAlign: msg.sender === course?.author ? 'left' : 'right',
                                    }}>
                                        <span style={{
                                            display: 'inline-block',
                                            background: msg.sender === course?.author ? 'white' : '#0C4B33',
                                            color: msg.sender === course?.author ? '#333' : 'white',
                                            padding: '8px 12px',
                                            borderRadius: '8px',
                                            fontSize: '13px',
                                            maxWidth: '80%',
                                            boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
                                        }}>
                                            <div style={{ fontSize: '11px', opacity: 0.7, marginBottom: '2px' }}>
                                                {msg.sender_username}
                                            </div>
                                            {msg.text}
                                        </span>
                                    </div>
                                ))
                            )}
                        </div>
                        <form onSubmit={handleSendMessage} style={{
                            display: 'flex',
                            gap: '8px',
                            padding: '12px',
                            borderTop: '1px solid #e2e8f0',
                        }}>
                            <input
                                type="text"
                                placeholder="Написать сообщение..."
                                value={newMessage}
                                onChange={e => setNewMessage(e.target.value)}
                                style={{
                                    flex: 1,
                                    padding: '8px',
                                    borderRadius: '6px',
                                    border: '1px solid #e2e8f0',
                                    fontSize: '13px',
                                }}
                            />
                            <button type="submit" disabled={sendingMessage} style={{
                                background: '#0C4B33',
                                color: 'white',
                                border: 'none',
                                borderRadius: '6px',
                                padding: '8px 12px',
                                cursor: 'pointer',
                            }}>
                                {sendingMessage ? '...' : '→'}
                            </button>
                        </form>
                    </div>
                )}

                <button
                    onClick={handleOpenChat}
                    style={{
                        width: '56px',
                        height: '56px',
                        borderRadius: '50%',
                        background: '#0C4B33',
                        color: 'white',
                        border: 'none',
                        fontSize: '24px',
                        cursor: 'pointer',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        marginLeft: 'auto',
                    }}
                >
                    💬
                </button>
            </div>
        </>
    );
}

export default LessonViewer;