import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__blockEditorTest = {};
const server = await createServer({
    configFile: false,
    ssr: { noExternal: ['react-router-dom', '@uiw/react-codemirror'] },
    server: { middlewareMode: true, hmr: false },
    plugins: [{
        name: 'block-editor-test-boundaries',
        enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0editor-api';
            if (source === 'react-router-dom') return '\0editor-router';
            if (source === '../components/pycharmDarcula') return '\0editor-theme';
            if (source === '../components/EditableTitle') return '\0editor-title';
            if (source === '../components/RichTextEditor' || source === '@uiw/react-codemirror') return '\0editor-field';
        },
        load(id) {
            if (id === '\0editor-api') return `export default {
                get: (...args) => globalThis.__blockEditorTest.get(...args),
                patch: (...args) => globalThis.__blockEditorTest.patch(...args),
            };`;
            if (id === '\0editor-router') return `
                export const useParams = () => ({ lessonId: 'lesson' });
                export const useNavigate = () => globalThis.__blockEditorTest.navigate;
                export const useSearchParams = () => [new URLSearchParams(globalThis.__blockEditorTest.search)];
                export const useBlocker = callback => {
                    globalThis.__blockEditorTest.shouldBlock = callback;
                    return globalThis.__blockEditorTest.blocker;
                };
            `;
            if (id === '\0editor-theme') return 'export const pycharmDarcula = [];';
            if (id === '\0editor-title') return `import React from 'react';
                export default props => React.createElement('h2', { 'data-editable': props.canEdit }, props.value);`;
            if (id === '\0editor-field') return `import React from 'react';
                export default props => React.createElement('textarea', {
                    value: props.value, onChange: event => props.onChange(event.target.value),
                });`;
        },
    }],
});
const { default: LessonEditor } = await server.ssrLoadModule('/src/pages/LessonEditor.jsx');
const { default: UnsavedBlockMarkers } = await server.ssrLoadModule('/src/components/UnsavedBlockMarkers.jsx');
after(() => server.close());

let blocks;
let patches;
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = { scrollTo() {}, addEventListener() {}, removeEventListener() {}, innerHeight: 800, scrollY: 0 };
    globalThis.ResizeObserver = class {
        constructor(callback) { fixture.resize = callback; }
        observe() {}
        disconnect() {}
    };
    globalThis.requestAnimationFrame = callback => { fixture.frame = callback; return 1; };
    globalThis.cancelAnimationFrame = () => {};
    globalThis.document = {
        getElementById: () => null,
        querySelector: () => null,
        documentElement: { scrollHeight: 4000 },
        body: {},
        createElement: () => ({
            set innerHTML(value) { this.textContent = value.replace(/<[^>]*>/g, ''); },
        }),
    };
    blocks = [
        { id: 'theory', type: 'TEXT', order_index: 1, content: { html: '<p>Theory</p>' } },
        { id: 'quiz', type: 'QUIZ', order_index: 2, content: { question: 'Which?', options: ['A', 'B'], correct_answer: 0 } },
        { id: 'code', type: 'CODE', order_index: 3, content: { prompt: 'Print', starter_code: 'print(1)', tests: [] } },
        { id: 'fill', type: 'FILL', order_index: 4, content: { prompt: 'Fill', template: 'print({{1}})' } },
    ];
    patches = [];
    fixture.search = '?block=theory';
    fixture.blocker = { state: 'unblocked' };
    fixture.navigate = t.mock.fn();
    fixture.get = async url => {
        if (url === '/auth/me/') return { data: { role: 'AUTHOR' } };
        if (url.startsWith('/lessons/')) return { data: { id: 'lesson', title: 'Lesson', lesson_position: 2 } };
        if (url.startsWith('/blocks/')) return { data: structuredClone(blocks) };
        throw Error(`Unexpected request: ${url}`);
    };
    fixture.patch = async (url, payload) => {
        patches.push({ url, payload });
        const block = blocks.find(row => url === `/blocks/${row.id}/`);
        Object.assign(block, structuredClone(payload));
        return { data: structuredClone(block) };
    };
    t.mock.method(console, 'error', () => {});
});

async function mount(t) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(LessonEditor)); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}

const cards = renderer => renderer.root.findAll(node => node.type === 'div' && node.props.id?.startsWith('edit-block-'));
const buttons = renderer => renderer.root.findAllByType('button');

for (const blockId of ['theory', 'quiz', 'code', 'fill']) {
    test(`block mode renders only ${blockId} and survives reopening`, async t => {
        fixture.search = `?block=${blockId}`;
        for (let i = 0; i < 2; i++) {
            const renderer = await mount(t);
            assert.deepEqual(cards(renderer).map(node => node.props.id), [`edit-block-${blockId}`]);
            const labels = buttons(renderer).map(node => node.children.join(''));
            assert.ok(!labels.some(label => /Копировать|Удалить|Вставить блок|Следующий урок/.test(label)));
            assert.equal(renderer.root.findAll(node => node.props['data-editable']).length, 0);
        }
    });
}

test('saving a block patches only that block and returns to its lesson anchor', async t => {
    const renderer = await mount(t);
    const untouched = structuredClone(blocks.slice(1));
    await act(async () => renderer.root.findByType('textarea').props.onChange({ target: { value: '<p>Updated theory</p>' } }));
    assert.equal(fixture.shouldBlock({ currentLocation: { pathname: '/edit/', search: '?block=theory' },
        nextLocation: { pathname: '/edit/', search: '' } }), true);
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Сохранить').props.onClick());
    assert.deepEqual(patches, [{ url: '/blocks/theory/', payload: { type: 'TEXT', content: { html: '<p>Updated theory</p>' } } }]);
    assert.deepEqual(blocks.slice(1), untouched);
    assert.equal(buttons(renderer).find(node => node.children.join('') === 'Сохранить').props.disabled, true);
    await act(async () => buttons(renderer).find(node => node.children.join('').includes('Назад к уроку')).props.onClick());
    assert.equal(fixture.navigate.mock.calls[0].arguments[0], '/lesson/lesson/#block-theory');
});

test('full lesson editor still renders every block and lesson controls', async t => {
    fixture.search = '';
    const renderer = await mount(t);
    assert.equal(cards(renderer).length, 4);
    assert.equal(renderer.root.findAll(node => node.props['data-editable']).length, 1);
    assert.ok(buttons(renderer).some(node => node.children.join('') === 'Удалить'));
});

test('unknown block never falls back to editing the entire lesson', async t => {
    fixture.search = '?block=missing';
    const renderer = await mount(t);
    assert.equal(cards(renderer).length, 0);
    assert.ok(JSON.stringify(renderer.toJSON()).includes('Блок не найден'));
});

test('switching block targets and full editor remounts with matching drafts', async t => {
    const renderer = await mount(t);
    fixture.search = '?block=quiz';
    await act(async () => renderer.update(React.createElement(LessonEditor)));
    assert.deepEqual(cards(renderer).map(node => node.props.id), ['edit-block-quiz']);
    fixture.search = '';
    await act(async () => renderer.update(React.createElement(LessonEditor)));
    assert.equal(cards(renderer).length, 4);
});

test('dirty markers jump to their block and disappear after saving', async t => {
    const focus = t.mock.fn();
    const scrollIntoView = t.mock.fn();
    document.getElementById = id => id === 'edit-block-theory'
        ? { getBoundingClientRect: () => ({ top: 1000 }), focus, scrollIntoView } : null;
    const renderer = await mount(t);
    const markers = () => buttons(renderer).filter(node => node.props.className === 'unsaved-block-markers__marker');
    assert.equal(markers().length, 0);
    await act(async () => renderer.root.findByType('textarea').props.onChange({ target: { value: '<p>Unsaved</p>' } }));
    assert.equal(markers().length, 1);
    assert.equal(markers()[0].props['aria-controls'], 'edit-block-theory');
    await act(async () => markers()[0].props.onClick());
    assert.deepEqual(focus.mock.calls[0].arguments, [{ preventScroll: true }]);
    assert.deepEqual(scrollIntoView.mock.calls.at(-1).arguments, [{ behavior: 'smooth', block: 'start' }]);
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Сохранить').props.onClick());
    assert.equal(markers().length, 0);
});

test('markers follow document positions, separate neighbours, and update on resize', async t => {
    let offset = 3000;
    document.getElementById = () => ({ getBoundingClientRect: () => ({ top: offset }) });
    const entries = [
        { elementId: 'edit-block-code', label: 'Unsaved code', dirty: true },
        { elementId: 'edit-new-new-1', label: 'Unsaved new theory', dirty: true },
        { elementId: 'saved', label: 'Saved', dirty: false },
    ];
    let renderer;
    await act(async () => { renderer = create(React.createElement(UnsavedBlockMarkers, { blocks: entries })); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    let markers = buttons(renderer);
    assert.equal(markers.length, 2);
    assert.equal(markers[1].props['aria-controls'], 'edit-new-new-1');
    assert.ok(markers[0].props.style.top > 500);
    assert.ok(markers[1].props.style.top - markers[0].props.style.top >= 24);
    offset = 100;
    await act(async () => { fixture.resize(); fixture.frame(); });
    markers = buttons(renderer);
    assert.ok(markers[0].props.style.top < 100);
    await act(async () => renderer.update(React.createElement(UnsavedBlockMarkers, {
        blocks: entries.map(entry => ({ ...entry, dirty: false })),
    })));
    assert.equal(buttons(renderer).length, 0);
});

test('failed saves retain markers; reverting removes them', async t => {
    document.getElementById = () => ({
        getBoundingClientRect: () => ({ top: 200 }), scrollIntoView() {},
    });
    window.confirm = () => true;
    fixture.patch = async () => { throw Error('Save failed'); };
    const renderer = await mount(t);
    const markers = () => buttons(renderer).filter(node => node.props.className === 'unsaved-block-markers__marker');
    await act(async () => renderer.root.findByType('textarea').props.onChange({ target: { value: '<p>Unsaved</p>' } }));
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Сохранить').props.onClick());
    assert.equal(markers().length, 1);
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Отменить изменения').props.onClick());
    assert.equal(markers().length, 0);
});
