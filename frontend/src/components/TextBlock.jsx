import { useEffect, useRef } from 'react';
import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import 'highlight.js/styles/atom-one-light.css';
import './TextBlock.css';

hljs.registerLanguage('python', python);

function TextBlock({ content }) {
    const ref = useRef(null);

    useEffect(() => {
        if (!ref.current) return;

        ref.current.querySelectorAll('pre code').forEach(block => {
            const pre = block.parentElement;

            pre.style.borderRadius = '6px';
            pre.style.fontSize = '15px';
            pre.style.lineHeight = '1.6';
            pre.style.fontFamily = "'JetBrains Mono', Consolas, monospace";
            pre.style.overflowX = 'auto';
            pre.style.marginBottom = '12px';
            pre.style.padding = '14px 18px';

            if (block.classList.contains('language-no-highlight')) {
                pre.style.background = '#f0f0f0';
                block.style.color = '#383a42';
            } else {
                pre.style.background = '#f0f0f0';
                hljs.highlightElement(block);
            }
        });
    }, [content]);

    return (
        <div style={{
            background: 'white',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
        }}>
            <div className="text-content" ref={ref} dangerouslySetInnerHTML={{ __html: content.html }} />
        </div>
    );
}

export default TextBlock;
