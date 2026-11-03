import { shuffledItems } from './sorting';

export function changeCell(selected, row, column, multiple, checked) {
    const cells = selected[row] || [];
    return { ...selected, [row]: multiple
        ? checked ? [...new Set([...cells, column])] : cells.filter(id => id !== column)
        : checked ? [column] : [] };
}

export function tableDisplay(content) {
    return {
        prompt: content.prompt,
        rows: content.shuffle_rows ? shuffledItems(content.rows) : [...content.rows],
        columns: content.shuffle_columns ? shuffledItems(content.columns) : [...content.columns],
        multiple_answers: content.multiple_answers === true,
        any_answer_correct: content.any_answer_correct === true,
        selected: Object.fromEntries(content.rows.map(row => [row.id, []])),
        result: null,
    };
}

export function restoreTable(content, progress, revision) {
    const snapshot = progress?.answer?.table_snapshot;
    // Restore the first success even after edits. An unfinished attempt against
    // an older revision starts with today's table instead of submitting old IDs.
    if (snapshot && (progress.is_correct === true || Date.parse(snapshot.revision) === Date.parse(revision))) {
        return { ...snapshot, selected: progress.answer.selected,
            result: { correct: progress.is_correct === true, comment: progress.feedback?.comment } };
    }
    return tableDisplay(content);
}
