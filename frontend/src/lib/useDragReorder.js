import { useCallback, useEffect, useRef, useState } from 'react';
import './dragReorder.css';

// Drop above or below a target; the API accepts the final 1-based position.
export function dropPosition(ids, source, target, after) {
    if (source === target || !ids.includes(source) || !ids.includes(target)) return null;
    const remaining = ids.filter(id => id !== source);
    const position = remaining.indexOf(target) + (after ? 1 : 0) + 1;
    return position === ids.indexOf(source) + 1 ? null : position;
}

export function useDragReorder({ ids, disabled, onMove }) {
    const [dragging, setDragging] = useState(null);
    const [target, setTarget] = useState(null);
    const sourceRef = useRef(null);
    const targetRef = useRef(null);
    const pointerRef = useRef(null);

    const clear = useCallback(() => {
        sourceRef.current = null;
        targetRef.current = null;
        pointerRef.current = null;
        setDragging(null);
        setTarget(null);
    }, []);

    useEffect(() => {
        if (dragging === null) return undefined;
        let frame;
        let lastTime;
        function scroll(time) {
            const y = pointerRef.current;
            const headerBottom = document.querySelector('.app-header')?.getBoundingClientRect().bottom || 0;
            const upperEdge = headerBottom + 80;
            const lowerEdge = window.innerHeight - 80;
            let speed = 0;
            if (y !== null && y < upperEdge) speed = -Math.min(1, (upperEdge - y) / 80);
            else if (y !== null && y > lowerEdge) speed = Math.min(1, (y - lowerEdge) / 80);
            const elapsed = lastTime === undefined ? 16 : Math.min(32, time - lastTime);
            if (speed) window.scrollBy(0, speed * elapsed * 0.8);
            lastTime = time;
            frame = requestAnimationFrame(scroll);
        }
        const track = event => { pointerRef.current = event.clientY; };
        const leave = event => { if (!event.relatedTarget) pointerRef.current = null; };
        const end = () => clear();
        document.addEventListener('dragover', track);
        document.addEventListener('dragleave', leave);
        document.addEventListener('dragend', end);
        document.addEventListener('drop', end);
        frame = requestAnimationFrame(scroll);
        return () => {
            cancelAnimationFrame(frame);
            document.removeEventListener('dragover', track);
            document.removeEventListener('dragleave', leave);
            document.removeEventListener('dragend', end);
            document.removeEventListener('drop', end);
        };
    }, [dragging, clear]);

    function getItemProps(id) {
        if (disabled) return {};
        return {
            className: ['reorder-item', dragging === id && 'reorder-item--dragging',
                target?.id === id && `reorder-item--${target.after ? 'after' : 'before'}`].filter(Boolean).join(' '),
            onDragOver(event) {
                if (sourceRef.current === null || id === sourceRef.current) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
                const rect = event.currentTarget.getBoundingClientRect();
                const next = { id, after: event.clientY > rect.top + rect.height / 2 };
                targetRef.current = next;
                if (target?.id !== next.id || target?.after !== next.after) setTarget(next);
            },
            onDragLeave(event) {
                if (event.currentTarget.contains(event.relatedTarget)) return;
                if (targetRef.current?.id === id) {
                    targetRef.current = null;
                    setTarget(null);
                }
            },
            onDrop(event) {
                if (sourceRef.current === null) return;
                event.preventDefault();
                event.stopPropagation();
                const rect = event.currentTarget.getBoundingClientRect();
                const position = dropPosition(ids, sourceRef.current, id, event.clientY > rect.top + rect.height / 2);
                const source = sourceRef.current;
                clear();
                if (position !== null) onMove(source, position);
            },
        };
    }

    function getHandleProps(id) {
        return {
            draggable: !disabled,
            disabled,
            onDragStart(event) {
                if (disabled) { event.preventDefault(); return; }
                sourceRef.current = id;
                pointerRef.current = event.clientY;
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', String(id));
                const card = event.currentTarget.closest('.reorder-item');
                if (card) event.dataTransfer.setDragImage(card, 24, 24);
                setDragging(id);
            },
            onDragEnd: clear,
        };
    }

    return { getItemProps, getHandleProps };
}
