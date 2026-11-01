import { useEffect, useState } from 'react';
import './UnsavedBlockMarkers.css';

// Native scrollbars cannot contain buttons. This rail follows their right edge
// and maps block locations onto the height of the document.
function UnsavedBlockMarkers({ blocks }) {
    const [layout, setLayout] = useState({ top: 0, height: 0, markers: [] });
    // Typing within an already dirty block doesn't change the marker list.
    const signature = JSON.stringify(blocks.filter(block => block.dirty).map(block => ({
        id: block.elementId, label: block.label,
    })));

    useEffect(() => {
        const targets = JSON.parse(signature);
        if (targets.length === 0) return undefined;
        let frame;
        function measure() {
            const header = document.querySelector('.app-header');
            const top = Math.max(0, header?.getBoundingClientRect().bottom || 0) + 12;
            const height = Math.max(0, window.innerHeight - top - 16);
            const documentHeight = Math.max(document.documentElement.scrollHeight, window.innerHeight);
            const markers = targets.flatMap(target => {
                const element = document.getElementById(target.id);
                if (!element) return [];
                const documentTop = element.getBoundingClientRect().top + window.scrollY;
                return [{ ...target, position: Math.max(0, Math.min(height - 24, documentTop / documentHeight * height)) }];
            }).sort((a, b) => a.position - b.position);

            // Separate neighbouring targets so each marker remains clickable.
            const spacing = Math.min(24, Math.max(0, (height - 24) / Math.max(1, markers.length - 1)));
            for (let i = 1; i < markers.length; i++) {
                markers[i].position = Math.max(markers[i].position, markers[i - 1].position + spacing);
            }
            if (markers.length && markers.at(-1).position > height - 24) {
                markers.at(-1).position = Math.max(0, height - 24);
                for (let i = markers.length - 2; i >= 0; i--) {
                    markers[i].position = Math.min(markers[i].position, markers[i + 1].position - spacing);
                }
            }
            setLayout({ top, height, markers });
        }
        function scheduleMeasure() {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(measure);
        }
        measure();
        const observer = new ResizeObserver(scheduleMeasure);
        observer.observe(document.body);
        const header = document.querySelector('.app-header');
        if (header) observer.observe(header);
        for (const target of targets) {
            const element = document.getElementById(target.id);
            if (element) observer.observe(element);
        }
        window.addEventListener('resize', scheduleMeasure);
        window.addEventListener('scroll', scheduleMeasure, { passive: true });
        return () => {
            cancelAnimationFrame(frame);
            observer.disconnect();
            window.removeEventListener('resize', scheduleMeasure);
            window.removeEventListener('scroll', scheduleMeasure);
        };
    }, [signature]);

    if (JSON.parse(signature).length === 0) return null;

    function jumpTo(id) {
        const element = document.getElementById(id);
        if (!element) return;
        element.focus({ preventScroll: true });
        element.scrollIntoView({
            behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
            block: 'start',
        });
    }

    return (
        <nav className="unsaved-block-markers" aria-label="Блоки с несохранёнными изменениями"
            style={{ top: layout.top, height: layout.height }}>
            {layout.markers.map(marker => (
                <button key={marker.id} type="button" className="unsaved-block-markers__marker"
                    style={{ top: marker.position }} aria-label={marker.label} title={marker.label}
                    aria-controls={marker.id} onClick={() => jumpTo(marker.id)} />
            ))}
        </nav>
    );
}

export default UnsavedBlockMarkers;
