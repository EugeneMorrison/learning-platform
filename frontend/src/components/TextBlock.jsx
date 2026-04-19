import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import 'highlight.js/styles/atom-one-light.css';
import './TextBlock.css';

hljs.registerLanguage('python', python);

const PRE_STYLE = 'background:#f0f0f0;border-radius:6px;padding:10px 16px;font-family:\'JetBrains Mono\',Consolas,monospace;font-size:14px;line-height:1.6;overflow-x:auto;margin-bottom:12px;';

function highlightPreBlocks(html) {
    // Match <pre ...>...</pre>, optionally with <code ...>...</code> inside
    return html.replace(/<pre\b[^>]*>([\s\S]*?)<\/pre>/gi, (_, inner) => {
        const codeMatch = inner.match(/<code\b([^>]*)>([\s\S]*?)<\/code>/i);
        const rawCode = codeMatch ? codeMatch[2] : inner;
        // Decode HTML entities (&lt; &gt; &amp; &quot; &#39;) back to plain text before highlighting
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

function TextBlock({ content }) {
    const processedHtml = highlightPreBlocks(content.html);

    return (
        <div style={{
            background: 'white',
            borderRadius: '8px',
            padding: '24px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
        }}>
            <div className="text-content" dangerouslySetInnerHTML={{ __html: processedHtml }} />
        </div>
    );
}

export default TextBlock;
