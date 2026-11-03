import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { htmlNodes } from '../lib/sortHtml.js';

const fixture = globalThis.__sortingTest = {};
const server = await createServer({ configFile: false, server: { middlewareMode: true, hmr: false },
    plugins: [{ name: 'sorting-test-boundaries', enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0sort-api';
            if (source === './DiscussionPanel') return '\0sort-discussion';
            if (['../lib/contentImages', '../lib/contentMath', '../lib/pythonHighlight'].includes(source)) return '\0sort-decoration';
        },
        load(id) {
            if (id === '\0sort-api') return 'export default { post: (...args) => globalThis.__sortingTest.post(...args) };';
            if (id === '\0sort-discussion') return 'export const DiscussionBadge = () => null;';
            if (id === '\0sort-decoration') return 'export const wrapImages = x => x; export const wrapTables = x => x; export const renderMath = x => x; export const highlightPreBlocks = x => x;';
        },
    }],
});
const { default: SortBlock } = await server.ssrLoadModule('/src/components/SortBlock.jsx');
after(() => server.close());

const items = [{ id: 'a', text: '  first' }, { id: 'b', text: 'second' }, { id: 'c', text: 'third' }];
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.document = { addEventListener() {}, removeEventListener() {}, querySelector: () => null };
    globalThis.window = { innerHeight: 800, scrollBy() {}, scrollTo() {} };
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = () => {};
    t.mock.method(console, 'error', () => {});
    t.mock.method(Math, 'random', () => 0.99);
    fixture.post = t.mock.fn(async (_url, payload) => ({ data: {
        is_correct: payload.answer.order.join() === 'a,b,c', recorded: true,
        feedback: { comment: 'Result comment' },
    } }));
});

async function mount(t, props = {}) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(SortBlock, {
        content: { prompt: 'Sort top to bottom', items }, blockId: 'sort', sortRevision: 'revision', ...props,
    })); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}
const order = renderer => renderer.root.findAllByProps({ className: 'sort-item__text' }).map(node => node.children.join(''));
const byLabel = (renderer, label) => renderer.root.findByProps({ 'aria-label': label });
const byText = (renderer, text) => renderer.root.findAllByType('button').find(button => button.children.join('') === text);

test('arrows submit IDs in displayed order and show failure comments', async t => {
    const submitted = t.mock.fn();
    const renderer = await mount(t, { onSubmitted: submitted });
    assert.equal(byLabel(renderer, 'Элемент 1: вверх').props.disabled, true);
    assert.equal(byLabel(renderer, 'Элемент 3: вниз').props.disabled, true);
    await act(async () => byLabel(renderer, 'Элемент 1: вниз').props.onClick());
    assert.deepEqual(order(renderer), ['second', '  first', 'third']);
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    assert.deepEqual(fixture.post.mock.calls[0].arguments, ['/progress/submit/', {
        block: 'sort', answer: { order: ['b', 'a', 'c'], sort_revision: 'revision' },
    }]);
    assert.equal(submitted.mock.calls[0].arguments[0].is_correct, false);
    assert.match(JSON.stringify(renderer.toJSON()), /Result comment/);
    assert.equal(byLabel(renderer, 'Элемент 1: вниз').props.disabled, true);
    await act(async () => byText(renderer, 'Попробовать снова').props.onClick());
    assert.ok(byText(renderer, 'Проверить'));
});

test('drag and drop moves the chosen item and success permits practice', async t => {
    const renderer = await mount(t);
    const handle = renderer.root.findAllByProps({ 'aria-label': 'Перетащить для изменения порядка' })[0];
    const transfer = { setData() {}, setDragImage() {} };
    await act(async () => handle.props.onDragStart({ dataTransfer: transfer, clientY: 40, currentTarget: { closest: () => null } }));
    const last = renderer.root.findAllByType('li')[2];
    await act(async () => last.props.onDrop({ dataTransfer: transfer, clientY: 100,
        preventDefault() {}, stopPropagation() {}, currentTarget: { getBoundingClientRect: () => ({ top: 50, height: 40 }) } }));
    assert.deepEqual(order(renderer), ['second', 'third', '  first']);
    await act(async () => byLabel(renderer, 'Элемент 3: вверх').props.onClick());
    await act(async () => byLabel(renderer, 'Элемент 2: вверх').props.onClick());
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    assert.ok(byText(renderer, 'Решить снова'));
    assert.match(JSON.stringify(renderer.toJSON()), /✅ Верно!/);
    await act(async () => byText(renderer, 'Решить снова').props.onClick());
    assert.ok(byText(renderer, 'Проверить'));
});

test('restores recorded order and original text before shuffling, including after author edits', async t => {
    const saved = { is_correct: true, answer: { items: [items[2], items[0], items[1]], html: false },
        feedback: { comment: 'Saved comment' } };
    const renderer = await mount(t, { savedProgress: saved, content: { prompt: 'Edited', items: [{ id: 'new', text: 'new item' }] } });
    assert.deepEqual(order(renderer), ['third', '  first', 'second']);
    assert.equal(Math.random.mock.calls.length, 0);
    assert.match(JSON.stringify(renderer.toJSON()), /Saved comment/);
});

test('failed requests retain the student order for another submission', async t => {
    fixture.post = async () => { throw { response: { data: { detail: 'Refresh this task' } } }; };
    const renderer = await mount(t);
    await act(async () => byLabel(renderer, 'Элемент 1: вниз').props.onClick());
    await act(async () => byText(renderer, 'Проверить').props.onClick());
    assert.deepEqual(order(renderer), ['second', '  first', 'third']);
    assert.match(JSON.stringify(renderer.toJSON()), /Refresh this task/);
    assert.equal(byText(renderer, 'Проверить').props.disabled, false);
});

test('plain text keeps markup literal and code indentation', async t => {
    const renderer = await mount(t, { content: { prompt: 'Sort', items: [{ id: 'x', text: '  <b>literal</b>' }, ...items] } });
    assert.ok(order(renderer).includes('  <b>literal</b>'));
    assert.equal(renderer.root.findAllByType('b').length, 0);
});

const text = value => ({ nodeType: 3, textContent: value });
const element = (tag, attrs = {}, children = []) => ({ nodeType: 1, tagName: tag.toUpperCase(), childNodes: children,
    hasAttribute: key => key in attrs, getAttribute: key => attrs[key] });

test('HTML allowlist keeps documented formatting and only abbr title', () => {
    const tags = ['b', 'i', 'strong', 'em', 'strike', 'h1', 'h2', 'h3', 'ol', 'li', 'ul', 'blockquote', 'code', 'abbr'];
    const nodes = tags.map(tag => element(tag, { title: 'Meaning', onclick: 'alert(1)', style: 'position:fixed', id: 'attack' }, [text('  hello')]));
    nodes.push(element('br'));
    const html = renderToStaticMarkup(React.createElement('div', null, htmlNodes(nodes)));
    for (const tag of tags) assert.match(html, new RegExp(`<${tag}[ >]`));
    assert.match(html, /<abbr title="Meaning">/);
    assert.match(html, /<br\/>/);
    assert.doesNotMatch(html, /onclick|style=|id=|alert/);
});

test('HTML drops executable elements, URLs and event handlers, preserving safe nested text', () => {
    const nodes = ['script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template'].map(tag =>
        element(tag, { src: 'https://example.com' }, [text('EXECUTABLE')]));
    nodes.push(element('img', { src: 'x', onerror: 'alert(1)' }));
    nodes.push(element('a', { href: 'javascript:alert(1)' }, [element('strong', {}, [text('safe')])]));
    assert.equal(renderToStaticMarkup(React.createElement('div', null, htmlNodes(nodes))), '<div><strong>safe</strong></div>');
});
