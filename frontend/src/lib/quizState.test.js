import test from 'node:test';
import assert from 'node:assert/strict';
import { orderOptions, restoreQuiz, validDisplayOrder } from './quizState.js';

const content = { question: 'Question', options: ['a', 'keys', 'c', 'd'] };
const solved = {
    is_correct: true,
    answer: { selected: 1, display_order: [3, 0, 1, 2], quiz_snapshot: { ...content } },
    feedback: { explanation: 'Correct explanation' },
};

test('multiple selections restore original identities and historical selection mode', () => {
    const snapshot = { ...content, multiple_answers: true };
    const progress = { is_correct: true, answer: {
        selected: [2, 0], display_order: [3, 2, 1, 0], quiz_snapshot: snapshot,
    } };
    const state = restoreQuiz({ ...content, multiple_answers: false }, progress);
    assert.deepEqual(state.selected, [2, 0]);
    assert.deepEqual(state.order.map(option => option.originalIndex), [3, 2, 1, 0]);
    assert.equal(state.snapshot.multiple_answers, true);
    assert.equal(state.historical, true);
    assert.equal(state.result.isCorrect, true);
    assert.notEqual(state.selected, progress.answer.selected);
});

test('multiple selections reject malformed saved indices and restore failed attempts', () => {
    const multi = { ...content, multiple_answers: true };
    for (const selected of [[], [0, 0], [true], [-1], [4], 1]) {
        assert.equal(restoreQuiz(multi, { answer: { selected } }).selected, null);
    }
    const state = restoreQuiz(multi, { is_correct: false, answer: { selected: [0, 2] } });
    assert.deepEqual(state.selected, [0, 2]);
    assert.equal(state.result.isCorrect, false);
});

test('reload and revisit preserve exact order and selected identity independently of randomness', () => {
    for (const random of [() => 0, () => 0.99, () => 0.4]) {
        const state = restoreQuiz(content, JSON.parse(JSON.stringify(solved)), null, random);
        assert.deepEqual(state.order.map(option => option.originalIndex), [3, 0, 1, 2]);
        assert.equal(state.order.find(option => option.originalIndex === state.selected).text, 'keys');
        assert.equal(state.order.findIndex(option => option.originalIndex === state.selected), 2);
        assert.equal(state.result.isCorrect, true);
    }
});

test('unanswered and incorrect questions retain fresh randomization', () => {
    assert.notDeepEqual(restoreQuiz(content, null, null, () => 0).order,
        restoreQuiz(content, null, null, () => 0.99).order);
    const wrong = { is_correct: false, answer: { selected: 0, display_order: [3, 0, 1, 2] } };
    const state = restoreQuiz(content, wrong, null, () => 0.99);
    assert.deepEqual(state.order.map(option => option.originalIndex), [0, 1, 2, 3]);
    assert.equal(state.selected, 0);
    assert.equal(state.result.isCorrect, false);
});

test('legacy solved work uses deterministic original order and retains completion', () => {
    const legacy = { is_correct: true, answer: { selected: 1 } };
    const state = restoreQuiz(content, legacy, null, () => { throw new Error('must not shuffle'); });
    assert.deepEqual(state.order.map(option => option.originalIndex), [0, 1, 2, 3]);
    assert.equal(state.selected, 1);
    assert.equal(state.result.isCorrect, true);
    legacy.answer.display_order = [3, 2, 1, 0]; // No trusted snapshot: still legacy.
    assert.deepEqual(restoreQuiz(content, legacy).order, state.order);
});

test('historical snapshot survives changed question and reordered, renamed or removed options', () => {
    for (const current of [
        { ...content, question: 'New question' },
        { ...content, options: ['keys', 'a', 'c', 'd'] },
        { ...content, options: ['replacement'] },
    ]) {
        const state = restoreQuiz(current, solved);
        assert.equal(state.historical, true);
        assert.deepEqual(state.snapshot, content);
        assert.equal(state.order.find(option => option.originalIndex === state.selected).text, 'keys');
        assert.equal(state.result.explanation, 'Correct explanation');
    }
    assert.equal(restoreQuiz(content, solved).historical, false);
});

test('student states and duplicate-text identities remain independent', () => {
    const other = { ...solved, answer: { ...solved.answer, display_order: [1, 2, 3, 0] } };
    assert.notDeepEqual(restoreQuiz(content, solved).order, restoreQuiz(content, other).order);
    const duplicate = { question: 'Q', options: ['same', 'same'] };
    const state = restoreQuiz(duplicate, {
        is_correct: true, answer: { selected: 1, display_order: [1, 0], quiz_snapshot: duplicate },
    });
    assert.equal(state.order[0].originalIndex, state.selected);
    assert.notEqual(state.order[1].originalIndex, state.selected);
});

test('invalid saved order falls back safely without losing completion', () => {
    for (const order of [null, [], [0, 1, 1, 3], [0, 1, 2, 4], [false, 1, 2, 3]]) {
        assert.equal(validDisplayOrder(order, 4), false);
        const state = restoreQuiz(content, { ...solved, answer: { ...solved.answer, display_order: order } });
        assert.deepEqual(state.order.map(option => option.originalIndex), [0, 1, 2, 3]);
        assert.equal(state.result.isCorrect, true);
    }
});

test('author shuffle setting and practice permutations do not mutate saved state', () => {
    const before = JSON.stringify(solved);
    assert.deepEqual(orderOptions(content.options, false).map(option => option.originalIndex), [0, 1, 2, 3]);
    orderOptions(content.options, true, () => 0);
    restoreQuiz(content, solved);
    assert.equal(JSON.stringify(solved), before);
});

test('legacy work edited after completion does not highlight an unprovable current answer', () => {
    const state = restoreQuiz(content, {
        is_correct: true, answer: { selected: 1 }, completed_at: '2026-10-30T00:00:00Z',
    }, '2026-10-31T00:00:00Z');
    assert.equal(state.legacyChanged, true);
    assert.equal(state.selected, null);
    assert.equal(state.result.isCorrect, true);
});
