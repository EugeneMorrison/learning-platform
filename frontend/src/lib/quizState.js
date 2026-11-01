// The index identifies an option within its question snapshot, not a screen row.
export function orderOptions(options, shuffle, random = Math.random) {
    const order = options.map((text, originalIndex) => ({ text, originalIndex }));
    if (shuffle) {
        for (let i = order.length - 1; i > 0; i--) {
            const j = Math.floor(random() * (i + 1));
            [order[i], order[j]] = [order[j], order[i]];
        }
    }
    return order;
}

export function reshuffleOptions(options, shuffle, previous, random = Math.random) {
    const next = orderOptions(options, shuffle, random);
    if (shuffle && next.length === previous.length
        && next.every((option, index) => option.text === previous[index].text)) {
        // Another random draw could repeat forever. Swap two different labels
        // once, comparing text rather than indices so duplicates cannot hide it.
        const different = next.findIndex(option => option.text !== next[0].text);
        if (different > 0) [next[0], next[different]] = [next[different], next[0]];
    }
    return next;
}

export function validDisplayOrder(order, count) {
    return Array.isArray(order) && order.length === count
        && order.every(index => Number.isInteger(index) && index >= 0 && index < count)
        && new Set(order).size === count;
}

export function restoreQuiz(content, progress, revision, random = Math.random) {
    const solved = progress?.is_correct === true;
    const answer = progress?.answer;
    const saved = solved ? answer?.quiz_snapshot : null;
    const snapshot = saved && typeof saved.question === 'string'
        && Array.isArray(saved.options) && saved.options.every(option => typeof option === 'string')
        ? { question: saved.question, options: saved.options,
            ...(saved.multiple_answers === true ? { multiple_answers: true } : {}) } : null;
    const shown = snapshot || content;
    const canonical = orderOptions(shown.options, false);
    const order = solved
        ? (snapshot && validDisplayOrder(answer?.display_order, canonical.length)
            ? answer.display_order.map(index => canonical[index]) : canonical)
        : orderOptions(content.options, content.shuffle_options !== false, random);
    const historical = Boolean(snapshot && (snapshot.question !== content.question
        || JSON.stringify(snapshot.options) !== JSON.stringify(content.options)
        || Boolean(snapshot.multiple_answers) !== Boolean(content.multiple_answers)));
    // For old records an author edit may have changed the meaning of an index.
    // Keep completion, but do not paint an unprovable current option green.
    const legacyChanged = Boolean(solved && !snapshot && revision && progress.completed_at
        && Date.parse(revision) > Date.parse(progress.completed_at));
    const validIndex = index => Number.isInteger(index) && index >= 0 && index < canonical.length;
    const selected = legacyChanged ? null : shown.multiple_answers
        ? (Array.isArray(answer?.selected) && answer.selected.length > 0
            && answer.selected.every(validIndex) && new Set(answer.selected).size === answer.selected.length
            ? [...answer.selected] : null)
        : (validIndex(answer?.selected) ? answer.selected : null);
    const result = solved || selected !== null ? {
        isCorrect: solved,
        explanation: progress?.feedback?.explanation || '',
    } : null;
    return { order, selected, result, snapshot, historical, legacyChanged };
}
