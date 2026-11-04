import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react';

// Shared by lesson configuration fields, including the formula dialog.
const AutoResizeTextarea = forwardRef(function AutoResizeTextarea({ value, style, rows = 1, ...props }, forwardedRef) {
    const ref = useRef(null);
    useImperativeHandle(forwardedRef, () => ref.current);

    useLayoutEffect(() => {
        const field = ref.current;
        if (!field) return undefined;
        const resize = () => {
            // Reset before measuring so deleting text also shrinks the field.
            // Borders are added because the measured scroll height excludes them.
            field.style.height = 'auto';
            field.style.height = `${field.scrollHeight + field.offsetHeight - field.clientHeight}px`;
        };
        resize();
        let width = field.getBoundingClientRect().width;
        const observer = new ResizeObserver(() => {
            const nextWidth = field.getBoundingClientRect().width;
            if (nextWidth === width) return;
            width = nextWidth;
            resize();
        });
        observer.observe(field);
        return () => observer.disconnect();
    }, [value]);

    return <textarea {...props} ref={ref} value={value} rows={rows}
        style={{ ...style, boxSizing: 'border-box', resize: 'none', overflowY: 'hidden' }} />;
});

export default AutoResizeTextarea;
