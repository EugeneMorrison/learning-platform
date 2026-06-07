import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';

hljs.registerLanguage('python', python);

const PRE_STYLE = "background:#f0f0f0;border-radius:6px;padding:10px 16px;font-family:'JetBrains Mono',Consolas,monospace;font-size:14px;line-height:1.6;overflow-x:auto;margin-bottom:12px;";

/**
 * Replace every <pre>...</pre> in an HTML string with a syntax-highlighted
 * Python code block. Shared by TextBlock and QuizBlock so theory text and
 * quiz questions highlight code identically. Code authored with the rich-text
 * editor arrives as <pre><code>...</code></pre>.
 */
export function highlightPreBlocks(html) {
    return (html || '').replace(/<pre\b[^>]*>([\s\S]*?)<\/pre>/gi, (_, inner) => {
        const codeMatch = inner.match(/<code\b([^>]*)>([\s\S]*?)<\/code>/i);
        const rawCode = codeMatch ? codeMatch[2] : inner;
        // Decode HTML entities back to plain text before highlighting.
        const decoded = rawCode
            .replace(/&lt;/g, '<')
            .replace(/&gt;/g, '>')
            .replace(/&quot;/g, '"')
            .replace(/&#39;/g, "'")
            .replace(/&amp;/g, '&');
        const highlighted = hljs.highlight(decoded, { language: 'python', ignoreIllegals: true }).value;
        return `<pre style="${PRE_STYLE}"><code class="hljs language-python">${highlighted}</code></pre>`;
    });
}
