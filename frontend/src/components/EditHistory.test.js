import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__historyTest = {};
const server = await createServer({
    configFile: false, server: { middlewareMode: true, hmr: false },
    plugins: [{ name: 'history-test-boundaries', enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0history-api';
            if (['../lib/contentImages', '../lib/contentMath', '../lib/pythonHighlight'].includes(source)) return '\0history-html';
        },
        load(id) {
            if (id === '\0history-api') return 'export default { get: (...args) => globalThis.__historyTest.get(...args) };';
            if (id === '\0history-html') return 'export const wrapImages = x => x, wrapTables = x => x, renderMath = x => x, highlightPreBlocks = x => x;';
        },
    }],
});
const { default: HistoryButton, EditHistoryDialog } = await server.ssrLoadModule('/src/components/EditHistory.jsx');
after(() => server.close());

const entry = id => ({ id, kind: 'block', action: 'updated', created_at: '2026-11-02T12:00:00Z', actor_name: 'Author',
    target_id: 'block', lesson_title: 'Strings', target_label: 'Theory', changed_fields: ['content'] });
const detail = id => ({ ...entry(id), before: { type: 'TEXT', content: { html: `Before ${id}` } },
    after: { type: 'TEXT', content: { html: `After ${id}` } } });
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.document = { documentElement: { classList: { add() {}, remove() {} } }, activeElement: null };
    fixture.get = t.mock.fn(async (_url, options) => ({ data: options.params.event
        ? detail(options.params.event) : { results: [entry(2)], next_cursor: null } }));
    t.mock.method(console, 'error', () => {});
});
async function mount(t, props = {}, Component = EditHistoryDialog) {
    const onClose = t.mock.fn();
    let renderer;
    await act(async () => { renderer = create(React.createElement(Component, { courseId: 'course', title: 'History', onClose, ...props })); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return { renderer, onClose };
}
const button = (renderer, label) => renderer.root.findAllByType('button').find(node => node.children.join('') === label);
const preview = renderer => renderer.root.findByProps({ className: 'edit-history__preview' });

test('history button loads nothing until opened, then scopes requests to its block', async t => {
    const { renderer } = await mount(t, { lessonId: 'lesson', blockId: 'block' }, HistoryButton);
    assert.equal(fixture.get.mock.calls.length, 0);
    await act(async () => button(renderer, 'История изменений').props.onClick());
    assert.deepEqual(fixture.get.mock.calls[0].arguments, ['/courses/course/history/', { params: { lesson: 'lesson', block: 'block' } }]);
    assert.equal(preview(renderer).findByProps({ className: 'text-content' }).props.dangerouslySetInnerHTML.__html, 'After 2');
});

test('before and after previews restore exactly the selected side', async t => {
    const onRestore = t.mock.fn(async () => true);
    const { renderer, onClose } = await mount(t, { onRestore, blockId: 'block' });
    await act(async () => button(renderer, 'До изменения').props.onClick());
    assert.equal(preview(renderer).findByProps({ className: 'text-content' }).props.dangerouslySetInnerHTML.__html, 'Before 2');
    await act(async () => button(renderer, 'Восстановить эту версию').props.onClick());
    assert.deepEqual(onRestore.mock.calls[0].arguments, [2, 'before']);
    assert.equal(onClose.mock.calls.length, 1);
});

test('failed or cancelled restoration keeps the history open', async t => {
    let fail = true;
    const { renderer, onClose } = await mount(t, { onRestore: async () => {
        if (fail) throw { response: { data: { detail: 'Newer revision exists' } } };
        return false;
    } });
    await act(async () => button(renderer, 'Восстановить эту версию').props.onClick());
    assert.ok(renderer.root.findByProps({ role: 'alert' }).children.join('').includes('Newer revision'));
    assert.equal(onClose.mock.calls.length, 0);
    fail = false;
    await act(async () => button(renderer, 'Восстановить эту версию').props.onClick());
    assert.equal(onClose.mock.calls.length, 0);
});

test('pagination appends older events and stale detail responses are ignored', async t => {
    let resolveOld;
    fixture.get = async (_url, options) => {
        if (options.params.event === 2) return new Promise(resolve => { resolveOld = resolve; });
        if (options.params.event) return { data: detail(options.params.event) };
        return { data: options.params.before ? { results: [entry(1)], next_cursor: null }
            : { results: [entry(2)], next_cursor: 2 } };
    };
    const { renderer } = await mount(t);
    await act(async () => button(renderer, 'Показать ещё').props.onClick());
    const entries = renderer.root.findAll(node => node.type === 'button' && node.props.className?.startsWith('edit-history__entry'));
    assert.equal(entries.length, 2);
    await act(async () => entries[1].props.onClick());
    await act(async () => resolveOld({ data: detail(2) }));
    assert.equal(preview(renderer).findByProps({ className: 'text-content' }).props.dangerouslySetInnerHTML.__html, 'After 1');
});

test('empty history explains when recording starts, and load failures can retry', async t => {
    let failed = true;
    fixture.get = async () => {
        if (failed) throw Error('Offline');
        return { data: { results: [], next_cursor: null } };
    };
    const { renderer } = await mount(t);
    assert.equal(renderer.root.findAllByProps({ role: 'alert' }).length, 1);
    failed = false;
    await act(async () => button(renderer, 'Повторить').props.onClick());
    assert.ok(JSON.stringify(renderer.toJSON()).includes('с момента включения этой функции'));
});

test('order history highlights the moved item and offers no block restore', async t => {
    fixture.get = async (_url, options) => ({ data: options.params.event
        ? { ...entry(2), before: { order: [{ id: 'block', type: 'TEXT' }] }, after: { order: [{ id: 'block', type: 'TEXT' }] } }
        : { results: [entry(2)], next_cursor: null } });
    const { renderer } = await mount(t, { onRestore() {} });
    assert.equal(preview(renderer).findAllByProps({ className: 'edit-history__moved' }).length, 1);
    assert.equal(button(renderer, 'Восстановить эту версию'), undefined);
});

test('course filters request lesson reordering separately from block edits', async t => {
    const { renderer } = await mount(t);
    await act(async () => renderer.root.findByProps({ 'aria-label': 'Объект истории' }).props.onChange({ target: { value: 'lesson' } }));
    await act(async () => renderer.root.findByProps({ 'aria-label': 'Действие в истории' }).props.onChange({ target: { value: 'reordered' } }));
    assert.ok(fixture.get.mock.calls.some(call => call.arguments[1].params.kind === 'lesson'
        && call.arguments[1].params.action === 'reordered' && !call.arguments[1].params.event));
});

test('history identifies the lesson explicitly and numbers each block version', async t => {
    const row = { ...entry(2), block_type: 'QUIZ', block_number: 3, lesson_number: 8 };
    fixture.get = async (_url, options) => ({ data: options.params.event ? {
        ...row, before: { type: 'QUIZ', block_number: 2, lesson_number: 8, content: { question: 'Before', options: [] } },
        after: { type: 'QUIZ', block_number: 3, lesson_number: 8, content: { question: 'After', options: [] } },
    } : { results: [row], next_cursor: null } });
    const { renderer } = await mount(t);
    const list = renderer.root.findByProps({ className: 'edit-history__list' });
    assert.ok(list.findAllByType('strong').some(node => node.children.join('') === 'Изменено · Тест 3'));
    assert.equal(list.findByProps({ className: 'edit-history__location' }).children.join(''), 'Урок 8: «Strings»');
    assert.equal(preview(renderer).findByProps({ className: 'edit-history__location' }).children.join(''), 'Урок 8: «Strings»');
    assert.equal(preview(renderer).findByType('strong').children.join(''), 'Тест 3');
    await act(async () => button(renderer, 'До изменения').props.onClick());
    assert.equal(preview(renderer).findByType('strong').children.join(''), 'Тест 2');
});

test('legacy numbers are visibly identified as current', async t => {
    fixture.get = async (_url, options) => ({ data: options.params.event ? {
        ...entry(2), lesson_number: 8, lesson_number_is_current: true,
        before: null, after: { type: 'QUIZ', block_number: 3, number_is_current: true, content: { question: 'Q' } },
    } : { results: [entry(2)], next_cursor: null } });
    const { renderer } = await mount(t);
    assert.equal(preview(renderer).findByType('strong').children.join(''), 'Тест 3 (номер сейчас)');
    assert.ok(preview(renderer).findByProps({ className: 'edit-history__location' }).children.join('').includes('номер сейчас'));
});
