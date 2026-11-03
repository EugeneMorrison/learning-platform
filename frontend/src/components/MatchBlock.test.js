import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__matchingTest = {};
const server = await createServer({ configFile: false, server: { middlewareMode: true, hmr: false },
    plugins: [{ name: 'matching-test-boundaries', enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0match-api';
            if (source === './DiscussionPanel') return '\0match-discussion';
            if (['../lib/contentImages', '../lib/contentMath', '../lib/pythonHighlight'].includes(source)) return '\0match-decoration';
        },
        load(id) {
            if (id === '\0match-api') return 'export default { post: (...args) => globalThis.__matchingTest.post(...args) };';
            if (id === '\0match-discussion') return 'export const DiscussionBadge = () => null;';
            if (id === '\0match-decoration') return 'export const wrapImages = x => x; export const wrapTables = x => x; export const renderMath = x => x; export const highlightPreBlocks = x => x;';
        },
    }],
});
const { default: MatchBlock } = await server.ssrLoadModule('/src/components/MatchBlock.jsx');
const { matchingDisplay } = await server.ssrLoadModule('/src/lib/matching.js');
after(() => server.close());

const left = [{ id: 'l1', text: 'Bulgaria' }, { id: 'l2', text: 'India' }, { id: 'l3', text: 'Extra' }];
const right = [{ id: 'r1', text: 'Sofia' }, { id: 'r2', text: 'New Delhi' }, { id: 'r3', text: '' }];
const content = { prompt: 'Match each country and capital', left, right, keep_left_order: true, html: false };
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.document = { addEventListener() {}, removeEventListener() {}, querySelector: () => null };
    globalThis.window = { innerHeight: 800, scrollBy() {}, scrollTo() {} };
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = () => {};
    t.mock.method(console, 'error', () => {});
    t.mock.method(Math, 'random', () => 0.99);
    fixture.post = t.mock.fn(async (_url, payload) => ({ data: {
        is_correct: payload.answer.right_order.join() === 'r1,r2,r3', recorded: true,
        feedback: { comment: 'Task feedback' },
    } }));
});

async function mount(t, props = {}) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(MatchBlock, {
        content, blockId: 'match', matchRevision: 'revision', ...props,
    })); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}
const cells = renderer => renderer.root.findAllByType('li').map(row => row.findAllByProps({ className: 'sort-item__text' }).map(node => node.children.join('')));
const byLabel = (renderer, label) => renderer.root.findByProps({ 'aria-label': label });
const byText = (renderer, text) => renderer.root.findAllByType('button').find(button => button.children.join('') === text);

for (const keep_left_order of [false, true]) {
    test(`author preview accepts the full paired content (fixed first column: ${keep_left_order})`, async t => {
        const authorContent = { prompt: content.prompt, html: false, keep_left_order,
            pairs: left.map((item, index) => ({ left: item, right: right[index] })),
            feedback_correct: 'Correct', feedback_incorrect: 'Try again' };
        const renderer = await mount(t, { content: authorContent });
        assert.deepEqual(cells(renderer), [['Bulgaria', 'Sofia'], ['India', 'New Delhi'], ['Extra']]);
        await act(async () => byText(renderer, 'Проверить').props.onClick());
        assert.ok(byText(renderer, 'Решить снова'));
        await act(async () => byText(renderer, 'Решить снова').props.onClick());
        assert.deepEqual(cells(renderer), [['Bulgaria', 'Sofia'], ['India', 'New Delhi'], ['Extra']]);
        assert.ok(byText(renderer, 'Проверить'));
        assert.equal(authorContent.pairs[0].left.id, 'l1');
    });
}

test('arrows reorder only the second column and submit exact displayed pairs', async t => {
    const onSubmitted = t.mock.fn();
    const renderer = await mount(t, { onSubmitted });
    assert.equal(byLabel(renderer, 'Правый элемент 1: вверх').props.disabled, true);
    assert.equal(byLabel(renderer, 'Правый элемент 3: вниз').props.disabled, true);
    await act(async () => byLabel(renderer, 'Правый элемент 1: вниз').props.onClick());
    assert.deepEqual(cells(renderer), [['Bulgaria', 'New Delhi'], ['India', 'Sofia'], ['Extra']]);
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    assert.deepEqual(fixture.post.mock.calls[0].arguments, ['/progress/submit/', {
        block: 'match', answer: { left_order: ['l1', 'l2', 'l3'], right_order: ['r2', 'r1', 'r3'], match_revision: 'revision' },
    }]);
    assert.equal(onSubmitted.mock.calls[0].arguments[0].is_correct, false);
    assert.match(JSON.stringify(renderer.toJSON()), /Task feedback/);
    assert.equal(byLabel(renderer, 'Правый элемент 1: вниз').props.disabled, true);
});

test('dragging right items matches them to the fixed left column and can solve the task', async t => {
    const renderer = await mount(t, { content: { ...content, right: [right[1], right[0], right[2]] } });
    const handle = renderer.root.findAllByProps({ 'aria-label': 'Перетащить для изменения порядка' })[0];
    assert.equal(renderer.root.findAllByProps({ 'aria-label': 'Перетащить для изменения порядка' }).length, 3);
    const transfer = { setData() {}, setDragImage() {} };
    await act(async () => handle.props.onDragStart({ dataTransfer: transfer, clientY: 40, currentTarget: { closest: () => null } }));
    const target = renderer.root.findAllByType('div').filter(node => node.props.onDrop)[1];
    await act(async () => target.props.onDrop({ dataTransfer: transfer, clientY: 100,
        preventDefault() {}, stopPropagation() {}, currentTarget: { getBoundingClientRect: () => ({ top: 50, height: 40 }) } }));
    assert.deepEqual(cells(renderer), [['Bulgaria', 'Sofia'], ['India', 'New Delhi'], ['Extra']]);
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()), /✅ Верно!/);
    assert.ok(byText(renderer, 'Решить снова'));
});

test('fixed first column survives retries; second column is shuffled every time', async t => {
    const renderer = await mount(t);
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    Math.random.mock.mockImplementation(() => 0);
    await act(async () => byText(renderer, 'Решить снова').props.onClick());
    assert.deepEqual(cells(renderer), [['Bulgaria', 'New Delhi'], ['India'], ['Extra', 'Sofia']]);
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    assert.ok(byText(renderer, 'Попробовать снова'));
    await act(async () => byText(renderer, 'Попробовать снова').props.onClick());
    assert.deepEqual(cells(renderer), [['Bulgaria', 'New Delhi'], ['India'], ['Extra', 'Sofia']]);
});

test('both columns are shuffled when the fixed-column setting is off', async () => {
    Math.random.mock.mockImplementation(() => 0);
    const display = matchingDisplay({ ...content, keep_left_order: false });
    assert.deepEqual(display.left.map(item => item.id), ['l2', 'l3', 'l1']);
    assert.deepEqual(display.right.map(item => item.id), ['r2', 'r3', 'r1']);
    assert.equal(Math.random.mock.calls.length, 4);
    assert.deepEqual(content.left, left);
    assert.deepEqual(content.right, right);
});

test('unmatched items on either side are visible and empty right items remain movable', async t => {
    const renderer = await mount(t, { content: { ...content, left: [left[0], left[1], { id: 'empty-left', text: '' }] } });
    assert.equal(renderer.root.findAllByProps({ className: 'match-empty' }).length, 2);
    await act(async () => byLabel(renderer, 'Правый элемент 3: вверх').props.onClick());
    assert.deepEqual(cells(renderer), [['Bulgaria', 'Sofia'], ['India'], ['New Delhi']]);
    assert.equal(renderer.root.findAllByProps({ className: 'match-empty' }).length, 2);
});

test('saved pairs restore before shuffling, including previous item text after author edits', async t => {
    const savedProgress = { is_correct: true,
        answer: { rows: [{ left: left[1], right: right[1] }, { left: left[0], right: right[0] }, { left: left[2], right: right[2] }], html: false },
        feedback: { comment: 'Saved feedback' } };
    const renderer = await mount(t, { savedProgress, content: { ...content, left: [{ id: 'new-left', text: 'Edited' }], right: [{ id: 'new-right', text: 'Edited' }] } });
    assert.equal(Math.random.mock.calls.length, 0);
    assert.deepEqual(cells(renderer), [['India', 'New Delhi'], ['Bulgaria', 'Sofia'], ['Extra']]);
    assert.match(JSON.stringify(renderer.toJSON()), /Saved feedback/);
});

test('failed requests retain work and make submission available again', async t => {
    fixture.post = async () => { throw { response: { data: { detail: 'Refresh this matching task' } } }; };
    const renderer = await mount(t);
    await act(async () => byLabel(renderer, 'Правый элемент 1: вниз').props.onClick());
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    assert.deepEqual(cells(renderer), [['Bulgaria', 'New Delhi'], ['India', 'Sofia'], ['Extra']]);
    assert.match(JSON.stringify(renderer.toJSON()), /Refresh this matching task/);
    assert.equal(byText(renderer, 'Проверить').props.disabled, false);
});

test('HTML setting applies to both columns through the shared formatting allowlist', async t => {
    // Supply an inert parsed DOM tree; allowlist security itself is covered in
    // SortBlock.test.js, shared by every matching item and history snapshot.
    const originalParser = globalThis.DOMParser;
    globalThis.DOMParser = class {
        parseFromString(value) {
            return { body: { childNodes: [{ nodeType: 1, tagName: 'STRONG',
                childNodes: [{ nodeType: 3, textContent: value.replace(/<[^>]*>/g, '') }],
                hasAttribute: () => false }] } };
        }
    };
    t.after(() => { globalThis.DOMParser = originalParser; });
    const renderer = await mount(t, { content: { ...content, html: true,
        left: left.map(item => ({ ...item, text: `<strong>${item.text}</strong>` })),
        right: right.map(item => ({ ...item, text: item.text ? `<strong>${item.text}</strong>` : '' })),
    } });
    assert.equal(renderer.root.findAllByType('strong').length, 5);
});
