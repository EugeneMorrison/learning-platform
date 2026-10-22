import { useEffect } from 'react';

// Phones: keep a fixed panel (the chat window, the discussion panel) above the
// on-screen keyboard. The keyboard shrinks the visual viewport but not the
// layout viewport that position: fixed uses, so the gap between them is
// exposed on the element as --chat-keyboard / --chat-viewport, and
// `keyboardClass` is set while the keyboard is open.
export function useKeyboardInset(ref, enabled, keyboardClass) {
    useEffect(() => {
        const vv = window.visualViewport;
        const el = ref.current;
        if (!enabled || !vv || !el) return undefined;
        function update() {
            const inset = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop));
            el.style.setProperty('--chat-keyboard', `${inset}px`);
            el.style.setProperty('--chat-viewport', `${Math.round(vv.height)}px`);
            // Ignore small differences (browser toolbars collapsing).
            el.classList.toggle(keyboardClass, inset > 80);
        }
        update();
        vv.addEventListener('resize', update);
        vv.addEventListener('scroll', update);
        return () => {
            vv.removeEventListener('resize', update);
            vv.removeEventListener('scroll', update);
        };
    }, [ref, enabled, keyboardClass]);
}
