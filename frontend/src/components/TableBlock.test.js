import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__tableTest = {};
const server = await createServer({ configFile: false, server: { middlewareMode: true, hmr: false },
    plugins: [{ name: 'table-test-boundaries', enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0table-api';
            if (source === './DiscussionPanel') return '\0table-discussion';
            if (['../lib/contentImages', '../lib/contentMath', '../lib/pythonHighlight'].includes(source)) return '\0table-decoration';
        },
        load(id) {
            if (id === '\0table-api') return 'export default { post: (...args) => globalThis.__tableTest.post(...args) };';
            if (id === '\0table-discussion') return 'export const DiscussionBadge = () => null;';
            if (id === '\0table-decoration') return 'export const wrapImages = x => x; export const wrapTables = x => x; export const renderMath = x => x; export const highlightPreBlocks = x => x;';
        },
    }],
});
const { default: TableBlock } = await server.ssrLoadModule('/src/components/TableBlock.jsx');
const { default: TableGrid } = await server.ssrLoadModule('/src/components/TableGrid.jsx');
after(() => server.close());

const rows = [{ id: 'r1', text: 'Australia' }, { id: 'r2', text: 'Austria' }];
const columns = [{ id: 'c1', text: 'English' }, { id: 'c2', text: 'German' }, { id: 'c3', text: 'Portuguese' }];
const revision = '2026-11-03T12:00:00Z';
const content = { prompt: 'Select official languages', rows, columns, multiple_answers: false, shuffle_rows: false, shuffle_columns: false };
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = { scrollTo() {} };
    t.mock.method(console, 'error', () => {});
    t.mock.method(Math, 'random', () => 0.99);
    fixture.solved = false;
    fixture.grade = selected => selected.r1.join() === 'c1' && selected.r2.join() === 'c2';
    fixture.post = t.mock.fn(async (_url, payload) => {
        const correct = fixture.grade(payload.answer.selected);
        const recorded = !fixture.solved;
        if (correct) fixture.solved = true;
        return { data: { is_correct: correct, recorded,
            feedback: { comment: correct ? 'Success feedback' : 'Failure feedback' } } };
    });
});

async function mount(t, props = {}) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(TableBlock, {
        content, blockId: 'table', tableRevision: revision, ...props,
    })); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}
const cell = (renderer, label) => renderer.root.findByProps({ 'aria-label': label });
const button = (renderer, label = 'Проверить') => renderer.root.findAllByType('button').find(node => node.children.join('') === label);
const choose = async (renderer, label, checked = true) => act(async () => cell(renderer, label).props.onChange({ target: { checked } }));
const colLabels = renderer => renderer.root.findByType('thead').findAllByType('th').slice(1).map(node => node.children.join(''));
const rowLabels = renderer => renderer.root.findByType('tbody').findAllByType('th').map(node => node.children.join(''));

test('single mode has independent radio groups and requires one answer per row', async t => {
    const renderer = await mount(t);
    const inputs = renderer.root.findAllByType('input');
    assert.ok(inputs.every(node => node.props.type === 'radio'));
    assert.equal(new Set(inputs.map(node => node.props.name)).size, 2);
    assert.equal(button(renderer).props.disabled, true);
    await choose(renderer, 'Australia — German');
    await choose(renderer, 'Australia — English');
    assert.equal(cell(renderer, 'Australia — German').props.checked, false);
    assert.equal(button(renderer).props.disabled, true);
    await choose(renderer, 'Austria — German');
    await act(async () => button(renderer).props.onClick());
    assert.deepEqual(fixture.post.mock.calls[0].arguments, ['/progress/submit/', {
        block: 'table', answer: { selected: { r1: ['c1'], r2: ['c2'] },
            row_order: ['r1', 'r2'], column_order: ['c1', 'c2', 'c3'], table_revision: revision },
    }]);
    assert.ok(renderer.root.findAllByType('input').every(node => node.props.disabled));
    assert.match(JSON.stringify(renderer.toJSON()), /Success feedback/);
});

test('incorrect checkboxes can be corrected immediately without resetting other cells or reshuffling', async t => {
    fixture.grade = selected => selected.r1.length === 2 && selected.r1.includes('c1') && selected.r1.includes('c2') && selected.r2.join() === 'c3';
    Math.random.mock.mockImplementation(() => 0);
    const submitted = t.mock.fn();
    const renderer = await mount(t, { content: { ...content, multiple_answers: true, shuffle_rows: true, shuffle_columns: true }, onSubmitted: submitted });
    const originalColumns = colLabels(renderer);
    const originalRows = rowLabels(renderer);
    await choose(renderer, 'Australia — English');
    await choose(renderer, 'Australia — Portuguese');
    await choose(renderer, 'Austria — Portuguese');
    await act(async () => button(renderer).props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()), /Failure feedback/);
    assert.equal(button(renderer, 'Попробовать снова'), undefined);
    assert.ok(renderer.root.findAllByType('input').every(node => !node.props.disabled));
    await choose(renderer, 'Australia — Portuguese', false);
    assert.equal(cell(renderer, 'Australia — English').props.checked, true);
    assert.equal(cell(renderer, 'Austria — Portuguese').props.checked, true);
    assert.doesNotMatch(JSON.stringify(renderer.toJSON()), /Failure feedback/);
    await choose(renderer, 'Australia — German');
    assert.deepEqual(colLabels(renderer), originalColumns);
    assert.deepEqual(rowLabels(renderer), originalRows);
    await act(async () => button(renderer).props.onClick());
    assert.equal(submitted.mock.calls.length, 2);
    assert.equal(submitted.mock.calls[1].arguments[0].is_correct, true);
    assert.deepEqual(fixture.post.mock.calls[1].arguments[1].answer.selected, { r1: ['c1', 'c2'], r2: ['c3'] });
});

test('single mode also permits correcting a wrong response in place', async t => {
    const renderer = await mount(t);
    await choose(renderer, 'Australia — Portuguese');
    await choose(renderer, 'Austria — German');
    await act(async () => button(renderer).props.onClick());
    await choose(renderer, 'Australia — English');
    assert.equal(cell(renderer, 'Austria — German').props.checked, true);
    assert.equal(cell(renderer, 'Australia — Portuguese').props.checked, false);
    await act(async () => button(renderer).props.onClick());
    assert.ok(button(renderer, 'Решить снова'));
});

test('row and column shuffle settings operate independently without mutating content', async t => {
    Math.random.mock.mockImplementation(() => 0);
    for (const shuffle_rows of [false, true]) {
        for (const shuffle_columns of [false, true]) {
            const renderer = await mount(t, { content: { ...content, shuffle_rows, shuffle_columns } });
            assert.deepEqual(rowLabels(renderer), shuffle_rows ? ['Austria', 'Australia'] : ['Australia', 'Austria']);
            assert.deepEqual(colLabels(renderer), shuffle_columns ? ['German', 'Portuguese', 'English'] : ['English', 'German', 'Portuguese']);
        }
    }
    assert.deepEqual(content.rows, rows);
    assert.deepEqual(content.columns, columns);
});

test('survey mode submits arbitrary answers and allows an empty multiple-choice response', async t => {
    fixture.grade = () => true;
    const renderer = await mount(t, { content: { ...content, any_answer_correct: true } });
    await choose(renderer, 'Australia — Portuguese');
    await choose(renderer, 'Austria — English');
    await act(async () => button(renderer).props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()), /Это опрос/);
    assert.ok(button(renderer, 'Решить снова'));
    const multiple = await mount(t, { content: { ...content, any_answer_correct: true, multiple_answers: true } });
    assert.equal(button(multiple).props.disabled, false);
    await act(async () => button(multiple).props.onClick());
    assert.deepEqual(fixture.post.mock.calls[1].arguments[1].answer.selected, { r1: [], r2: [] });
});

test('author preview renders the full API shape without prefilling correct answers', async t => {
    const renderer = await mount(t, { content: { ...content, correct_cells: { r1: ['c1'], r2: ['c2'] },
        feedback_correct: 'PRIVATE-COMMENT', feedback_incorrect: 'PRIVATE-FAILURE' } });
    assert.equal(renderer.root.findAllByType('input').filter(node => node.props.checked).length, 0);
    assert.doesNotMatch(JSON.stringify(renderer.toJSON()), /PRIVATE/);
    assert.deepEqual(rowLabels(renderer), ['Australia', 'Austria']);
});

test('first success restores its original display after edits; practice uses current content', async t => {
    const snapshot = { ...content, revision, rows: [...rows].reverse(), columns: [...columns].reverse() };
    const selected = { r1: ['c1'], r2: ['c2'] };
    const savedProgress = { is_correct: true, answer: { selected, table_snapshot: snapshot }, feedback: { comment: 'Original success' } };
    const renderer = await mount(t, { content: { ...content, rows: [{ id: 'new', text: 'Edited row' }], multiple_answers: true }, savedProgress });
    assert.deepEqual(rowLabels(renderer), ['Austria', 'Australia']);
    assert.deepEqual(colLabels(renderer), ['Portuguese', 'German', 'English']);
    assert.equal(cell(renderer, 'Australia — English').props.checked, true);
    assert.equal(cell(renderer, 'Austria — German').props.checked, true);
    assert.match(JSON.stringify(renderer.toJSON()), /Original success/);
    assert.equal(Math.random.mock.calls.length, 0);
    await act(async () => button(renderer, 'Решить снова').props.onClick());
    assert.deepEqual(rowLabels(renderer), ['Edited row']);
    assert.ok(renderer.root.findAllByType('input').every(node => node.props.type === 'checkbox' && !node.props.checked));
    assert.deepEqual(savedProgress.answer.selected, selected);
});

test('unfinished saved attempts remain editable; stale unfinished snapshots use current table', async t => {
    const savedProgress = { is_correct: false, answer: { selected: { r1: ['c3'], r2: ['c2'] },
        table_snapshot: { ...content, revision: '2026-11-03T12:00:00+00:00' } }, feedback: { comment: 'Saved failure' } };
    const renderer = await mount(t, { savedProgress });
    assert.equal(cell(renderer, 'Australia — Portuguese').props.checked, true);
    assert.match(JSON.stringify(renderer.toJSON()), /Saved failure/);
    await choose(renderer, 'Australia — English');
    assert.equal(cell(renderer, 'Austria — German').props.checked, true);
    const stale = await mount(t, { savedProgress, tableRevision: '2026-11-04T12:00:00Z' });
    assert.equal(stale.root.findAllByType('input').filter(node => node.props.checked).length, 0);
    assert.equal(button(stale).props.disabled, true);
});

test('network failure preserves selected cells and permits another submission', async t => {
    fixture.post = async () => { throw { response: { data: { detail: 'Temporary failure' } } }; };
    const renderer = await mount(t);
    await choose(renderer, 'Australia — English');
    await choose(renderer, 'Austria — German');
    await act(async () => button(renderer).props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()), /Temporary failure/);
    assert.equal(button(renderer).props.disabled, false);
    assert.equal(cell(renderer, 'Australia — English').props.checked, true);
    assert.equal(cell(renderer, 'Austria — German').props.checked, true);
});

test('separate history grids use different native radio groups even for the same saved rows', async t => {
    let renderer;
    await act(async () => { renderer = create(React.createElement(React.Fragment, null,
        React.createElement(TableGrid, { rows, columns, namePrefix: 'history', selected: { r1: ['c1'] } }),
        React.createElement(TableGrid, { rows, columns, namePrefix: 'history', selected: { r1: ['c3'] } }))); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    const grids = renderer.root.findAllByType('table');
    assert.notEqual(grids[0].findAllByType('input')[0].props.name, grids[1].findAllByType('input')[0].props.name);
    assert.ok(renderer.root.findAllByType('input').every(node => node.props.disabled));
});
