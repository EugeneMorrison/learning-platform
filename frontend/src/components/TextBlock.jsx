import 'highlight.js/styles/atom-one-light.css';
import './blocks.css';
import { DiscussionBadge } from './DiscussionPanel';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages, wrapTables } from '../lib/contentImages';
import { renderMath } from '../lib/contentMath';

function TextBlock({ content, blockId, onAsk, discussion }) {
    const processedHtml = wrapTables(wrapImages(renderMath(highlightPreBlocks(content.html))));

    return (
        <div className="lesson-block">
            {(onAsk || discussion) && (
                <div className="lesson-block__head">
                    {onAsk && (
                        <button type="button" className="lesson-block__ask" onClick={() => onAsk()}>
                            Задать вопрос
                        </button>
                    )}
                    <DiscussionBadge blockId={blockId} discussion={discussion} subject="теории" />
                </div>
            )}
            <div className="text-content" dangerouslySetInnerHTML={{ __html: processedHtml }} />
        </div>
    );
}

export default TextBlock;
