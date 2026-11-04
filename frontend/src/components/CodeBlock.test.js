import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act, StrictMode } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__codeDraftTest = {};
const server = await createServer({
    configFile: false,
    ssr: { noExternal: ['@uiw/react-codemirror', '@codemirror/lang-python'] },
    server: { middlewareMode: true, hmr: false },
    plugins: [{
        name: 'code-draft-test-boundaries',
        enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0draft-api';
            if (source === '@uiw/react-codemirror') return '\0draft-editor';
            if (source === '@codemirror/lang-python' || source === './pycharmDarcula') return '\0draft-theme';
            if (source === '../lib/contentImages') return '\0draft-images';
            if (source === '../lib/contentMath') return '\0draft-math';
            if (source === './DiscussionPanel') return '\0draft-discussion';
        },
        load(id) {
            if (id === '\0draft-api') return `export default {
                post: (...args) => globalThis.__codeDraftTest.post(...args),
            };`;
            if (id === '\0draft-editor') return `import React from 'react';
                export default function Editor({ value, onChange }) {
                    return React.createElement('textarea', { 'aria-label': 'Code', value, onChange });
                }`;
            if (id === '\0draft-theme') return 'export const python = () => []; export const pycharmDarcula = [];';
            if (id === '\0draft-images') return 'export const wrapImages = html => html; export const wrapTables = html => html;';
            if (id === '\0draft-math') return 'export const renderMath = html => html;';
            if (id === '\0draft-discussion') return 'export const DiscussionBadge = () => null;';
        },
    }],
});
const { default: CodeBlock } = await server.ssrLoadModule('/src/components/CodeBlock.jsx');
after(() => server.close());

const content = { prompt: 'Write code', starter_code: '# Start here', tests: [] };
const freshCode = '# Start here\n\n\n';
let storage;

beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    storage = new Map();
    globalThis.localStorage = {
        getItem: key => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
    };
    globalThis.document = { addEventListener() {}, removeEventListener() {} };
    fixture.post = async () => ({ data: { status: 'success', total: 1 } });
    t.mock.method(console, 'error', () => {});
});

async function mount(t, props = {}, strict = false) {
    let renderer;
    await act(async () => {
        const block = React.createElement(CodeBlock, { userId: 'student-a', blockId: 'block-a', content, ...props });
        renderer = create(strict ? React.createElement(StrictMode, null, block) : block);
    });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}

function editor(renderer) {
    return renderer.root.findByProps({ 'aria-label': 'Code' });
}

async function edit(renderer, code) {
    await act(async () => editor(renderer).props.onChange(code));
}

async function click(renderer, text) {
    const button = renderer.root.findAllByType('button').find(node => node.props.children === text);
    assert.ok(button, `Expected action: ${text}`);
    await act(async () => button.props.onClick());
}

test('draft survives leaving an assignment, reloads and logout/login with a new token', async t => {
    const page = await mount(t);
    const code = 'name = "ученик"\nprint(name)\n';
    // Persistence is synchronous, before React commits or a navigation starts.
    await act(async () => {
        editor(page).props.onChange(code);
        assert.equal([...storage.values()][0], code);
    });
    await act(async () => page.unmount());
    const otherLesson = await mount(t, { blockId: 'theory-next-task' });
    assert.equal(editor(otherLesson).props.value, freshCode);
    for (const token of [null, 'new-login-token', 'refreshed-token']) {
        if (token) localStorage.setItem('access_token', token);
        else storage.delete('access_token');
        const reopened = await mount(t, {}, true);
        assert.equal(editor(reopened).props.value, code);
    }
});

test('drafts stay separate by account and assignment', async t => {
    const first = await mount(t);
    await edit(first, 'print("first")');
    const otherAccount = await mount(t, { userId: 'student-b' });
    assert.equal(editor(otherAccount).props.value, freshCode);
    await edit(otherAccount, 'print("second")');
    const otherTask = await mount(t, { blockId: 'block-b' });
    assert.equal(editor(otherTask).props.value, freshCode);
    await edit(otherTask, 'print("third")');
    assert.equal(editor(await mount(t)).props.value, 'print("first")');
    assert.equal(editor(await mount(t, { userId: 'student-b' })).props.value, 'print("second")');
    assert.equal(editor(await mount(t, { blockId: 'block-b' })).props.value, 'print("third")');
});

test('an empty draft overrides submitted and starter code without writing on mount', async t => {
    const savedProgress = { answer: { code: 'print("submitted")' } };
    const page = await mount(t, { savedProgress });
    assert.equal(editor(page).props.value, savedProgress.answer.code);
    assert.equal(storage.size, 0);
    await edit(page, '');
    const reopened = await mount(t, { savedProgress }, true);
    assert.equal(editor(reopened).props.value, '');
});

test('an empty submitted answer is preserved when no draft exists', async t => {
    const page = await mount(t, { savedProgress: { answer: { code: '' } } });
    assert.equal(editor(page).props.value, '');
});

test('run and failed submission preserve the draft and send the restored code', async t => {
    const page = await mount(t);
    await edit(page, 'print("unfinished")');
    const reopened = await mount(t);
    const calls = [];
    fixture.post = async (url, payload) => {
        calls.push({ url, payload });
        if (url === '/run-tests/') throw Error('Network unavailable');
        return { data: { stdout: 'unfinished' } };
    };
    await click(reopened, '▶ Запустить код');
    await click(reopened, '✔ Отправить');
    assert.deepEqual(calls.map(call => call.url), ['/run-code/', '/run-tests/']);
    assert.ok(calls.every(call => call.payload.code === 'print("unfinished")'));
    assert.equal(editor(await mount(t)).props.value, 'print("unfinished")');
});

test('version picker offers only 3.12 and 3.14 and sends the selected version to both endpoints', async t => {
    const page = await mount(t);
    const picker = () => page.root.findByProps({ className: 'version-select__btn' });
    assert.equal(picker().findAllByType('span')[0].children.join(''), 'Python 3.12');
    await act(async () => picker().props.onClick());
    const options = page.root.findAll(node => node.type === 'div' && node.props.className?.split(' ').includes('version-select__item'));
    assert.deepEqual(options.map(node => node.children.join('')), ['Python 3.12', 'Python 3.14']);
    await act(async () => options[1].props.onClick());
    const calls = [];
    fixture.post = async (url, payload) => {
        calls.push({ url, payload });
        return { data: { stdout: 'ok', status: 'success', total: 1 } };
    };
    await click(page, '▶ Запустить код');
    await click(page, '✔ Отправить');
    assert.deepEqual(calls.map(call => [call.url, call.payload.version]), [
        ['/run-code/', 'Python 3.14'], ['/run-tests/', 'Python 3.14'],
    ]);
});

test('a submission response does not discard newer edits made while grading', async t => {
    const page = await mount(t);
    await edit(page, 'print("submitted")');
    let finish;
    fixture.post = () => new Promise(resolve => { finish = resolve; });
    const button = page.root.findAllByType('button').find(node => node.props.children === '✔ Отправить');
    let pending;
    await act(async () => { pending = button.props.onClick(); });
    await edit(page, 'print("newer draft")');
    await act(async () => {
        finish({ data: { status: 'success', total: 1 } });
        await pending;
    });
    assert.equal(editor(await mount(t, {
        savedProgress: { is_correct: true, answer: { code: 'print("submitted")' } },
    })).props.value, 'print("newer draft")');
});

test('reset saves the starter code instead of resurrecting the previous draft or submission', async t => {
    const savedProgress = { is_correct: true, answer: { code: 'print("solved")' } };
    const page = await mount(t, { savedProgress });
    await edit(page, 'print("practice")');
    await click(page, '🔄 Сбросить');
    assert.equal(editor(page).props.value, freshCode);
    assert.equal(editor(await mount(t, { savedProgress })).props.value, freshCode);
});

test('storage failures warn without blocking edits, then recover on the next successful save', async t => {
    t.mock.method(localStorage, 'getItem', () => { throw Error('Storage disabled'); });
    const page = await mount(t);
    assert.equal(editor(page).props.value, freshCode);
    assert.equal(page.root.findAllByProps({ role: 'alert' }).length, 1);
    const setItem = t.mock.method(localStorage, 'setItem', () => { throw Error('Quota exceeded'); });
    await edit(page, 'print("keep in memory")');
    assert.equal(editor(page).props.value, 'print("keep in memory")');
    assert.equal(page.root.findAllByProps({ role: 'alert' }).length, 1);
    setItem.mock.restore();
    await edit(page, 'print("saved again")');
    assert.equal(page.root.findAllByProps({ role: 'alert' }).length, 0);
    assert.equal([...storage.values()][0], 'print("saved again")');
});

test('missing account identity never reads or writes another student draft', async t => {
    const owner = await mount(t);
    await edit(owner, 'private work');
    const page = await mount(t, { userId: undefined });
    assert.equal(editor(page).props.value, freshCode);
    await edit(page, 'temporary work');
    assert.equal(page.root.findAllByProps({ role: 'alert' }).length, 1);
    assert.equal(storage.size, 1);
    assert.equal(editor(await mount(t)).props.value, 'private work');
});
