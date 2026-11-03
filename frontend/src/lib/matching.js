import { shuffledItems } from './sorting';

export function matchingDisplay(content) {
    // Authors receive the editor's full pairs, while students receive two
    // independent lists. The lesson viewer and retries must support both.
    const left = content.left ?? content.pairs.map(pair => pair.left);
    const right = content.right ?? content.pairs.map(pair => pair.right);
    return {
        left: content.keep_left_order ? [...left] : shuffledItems(left),
        right: shuffledItems(right),
        html: content.html === true,
    };
}

export function restoreMatching(content, progress) {
    if (!progress?.answer?.rows?.length) return matchingDisplay(content);
    return {
        left: progress.answer.rows.map(row => row.left),
        right: progress.answer.rows.map(row => row.right),
        html: progress.answer.html === true,
    };
}
