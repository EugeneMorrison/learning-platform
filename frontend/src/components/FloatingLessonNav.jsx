import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import './FloatingLessonNav.css';

function FloatingLessonNav({ previousLessonId, nextLessonId, topRef, bottomRef, editor = false, previewTo }) {
    const [visible, setVisible] = useState(false);
    const [top, setTop] = useState(0);
    const [focused, setFocused] = useState(false);

    useEffect(() => {
        if (!previousLessonId && !nextLessonId) return undefined;
        const targets = [...new Set([topRef.current, bottomRef.current].filter(Boolean))];
        if (!targets.length) return undefined;
        const header = document.querySelector('.app-header');
        let observer;
        function observe() {
            observer?.disconnect();
            const headerBottom = Math.max(0, header?.getBoundingClientRect().bottom || 0);
            setTop(headerBottom + 8);
            const visibility = new Map();
            observer = new IntersectionObserver(entries => {
                for (const entry of entries) visibility.set(entry.target, entry.isIntersecting);
                // Wait until both original rows have been measured to avoid flashing.
                if (visibility.size === targets.length) setVisible(![...visibility.values()].some(Boolean));
            }, { rootMargin: `-${headerBottom}px 0px 0px 0px` });
            targets.forEach(target => observer.observe(target));
        }
        observe();
        const resize = new ResizeObserver(observe);
        if (header) resize.observe(header);
        window.addEventListener('resize', observe);
        return () => {
            observer.disconnect();
            resize.disconnect();
            window.removeEventListener('resize', observe);
        };
    }, [previousLessonId, nextLessonId, topRef, bottomRef]);

    if ((!visible && !focused) || (!previousLessonId && !nextLessonId)) return null;
    const path = id => `/lesson/${id}/${editor ? 'edit/' : ''}`;
    const onClick = editor ? undefined : () => window.scrollTo(0, 0);
    return (
        <nav className={`floating-lesson-nav${editor ? ' floating-lesson-nav--editor' : ''}`} style={{ top }} aria-label="Переход между уроками"
            onFocus={() => setFocused(true)} onBlur={event => {
                if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
            }}>
            <div className="floating-lesson-nav__side floating-lesson-nav__previous">
                {previousLessonId && <Link className="btn btn-secondary btn-sm" to={path(previousLessonId)} onClick={onClick}>
                    ← Предыдущий урок
                </Link>}
            </div>
            <div className="floating-lesson-nav__side floating-lesson-nav__next">
                {editor && previewTo && <Link className="btn btn-secondary btn-sm" to={previewTo}>👁 Предпросмотр</Link>}
                {nextLessonId && <Link className="btn btn-secondary btn-sm" to={path(nextLessonId)} onClick={onClick}>
                    Следующий урок →
                </Link>}
            </div>
        </nav>
    );
}

export default FloatingLessonNav;
