import 'highlight.js/styles/atom-one-light.css';
import './blocks.css';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages } from '../lib/contentImages';

function TextBlock({ content }) {
    const processedHtml = wrapImages(highlightPreBlocks(content.html));

    return (
        <div className="lesson-block">
            <div className="text-content" dangerouslySetInnerHTML={{ __html: processedHtml }} />
        </div>
    );
}

export default TextBlock;
