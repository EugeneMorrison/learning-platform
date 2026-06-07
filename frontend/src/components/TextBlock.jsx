import 'highlight.js/styles/atom-one-light.css';
import './TextBlock.css';
import { highlightPreBlocks } from '../lib/pythonHighlight';

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
