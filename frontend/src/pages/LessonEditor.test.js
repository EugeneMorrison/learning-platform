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
            if (source === '../components/RichTextEditor' || source === './RichTextEditor' || source === '@uiw/react-codemirror') return '\0editor-field';
        },
        load(id) {
            if (id === '\0editor-api') return `export default {
                get: (...args) => globalThis.__blockEditorTest.get(...args),
                patch: (...args) => globalThis.__blockEditorTest.patch(...args),
                post: (...args) => globalThis.__blockEditorTest.post(...args),
            };`;
            if (id === '\0editor-router') return `
                export const useParams = () => ({ lessonId: 'lesson' });
                export const useNavigate = () => globalThis.__blockEditorTest.navigate;
                export const useSearchParams = () => [new URLSearchParams(globalThis.__blockEditorTest.search), globalThis.__blockEditorTest.setSearchParams];
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
const { dropPosition } = await server.ssrLoadModule('/src/lib/useDragReorder.js');
after(() => server.close());

let blocks;
let patches;
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = { scrollTo: t.mock.fn(), addEventListener() {}, removeEventListener() {}, innerHeight: 800, scrollY: 0 };
    globalThis.ResizeObserver = class {
        constructor(callback) { fixture.resize = callback; }
        observe() {}
        disconnect() {}
    };
    globalThis.requestAnimationFrame = callback => { fixture.frame = callback; return 1; };
    globalThis.cancelAnimationFrame = () => {};
    globalThis.document = {
        addEventListener() {},
        removeEventListener() {},
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
    fixture.search = '';
    fixture.setSearchParams = t.mock.fn(updater => {
        const params = updater(new URLSearchParams(fixture.search));
        fixture.search = params.size ? `?${params}` : '';
    });
    fixture.blocker = { state: 'unblocked' };
    fixture.navigate = t.mock.fn();
    fixture.get = async url => {
        if (url === '/auth/me/') return { data: { role: 'AUTHOR' } };
        if (url === '/lessons/outline/') return { data: [
            { id: 'lesson', title: 'Data Input', position: 1 }, { id: 'variables', title: 'Variables', position: 2 },
        ] };
        if (url.startsWith('/lessons/')) return { data: { id: 'lesson', course: 'course', title: 'Lesson', lesson_position: 2 } };
        if (url.startsWith('/blocks/')) return { data: structuredClone(blocks) };
        throw Error(`Unexpected request: ${url}`);
    };
    fixture.patch = async (url, payload) => {
        patches.push({ url, payload });
        const block = blocks.find(row => url === `/blocks/${row.id}/`);
        Object.assign(block, structuredClone(payload));
        return { data: structuredClone(block) };
    };
    fixture.post = t.mock.fn(async (url, payload) => {
        const index = blocks.findIndex(block => url === `/blocks/${block.id}/reorder/`);
        if (index < 0) throw Error(`Unexpected request: ${url}`);
        const [moved] = blocks.splice(index, 1);
        blocks.splice(payload.new_order - 1, 0, moved);
        return { data: structuredClone(blocks) };
    });
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
    test(`block link opens the full editor and scrolls to ${blockId}`, async t => {
        fixture.search = `?block=${blockId}&keep=value`;
        const scrollIntoView = t.mock.fn();
        document.getElementById = id => id === `edit-block-${blockId}` ? { scrollIntoView } : null;
        const renderer = await mount(t);
        assert.deepEqual(cards(renderer).map(node => node.props.id), blocks.map(block => `edit-block-${block.id}`));
        assert.deepEqual(scrollIntoView.mock.calls[0].arguments, [{ block: 'start' }]);
        assert.equal(fixture.search, '?keep=value');
        assert.deepEqual(fixture.setSearchParams.mock.calls[0].arguments[1], { replace: true });
        const labels = buttons(renderer).map(node => node.children.join(''));
        assert.ok(labels.includes('⧉ Копировать'));
        assert.ok(labels.includes('Удалить'));
        assert.equal(renderer.root.findAll(node => node.props['data-editable']).length, 1);
        assert.equal(buttons(renderer).filter(node => node.props.draggable).length, 4);
    });
}

test('saving a block patches only that block and returns to its lesson anchor', async t => {
    const renderer = await mount(t);
    const untouched = structuredClone(blocks.slice(1));
    await act(async () => cards(renderer)[0].findByType('textarea').props.onChange({ target: { value: '<p>Updated theory</p>' } }));
    assert.equal(fixture.shouldBlock({ currentLocation: { pathname: '/edit/', search: '?block=theory' },
        nextLocation: { pathname: '/edit/', search: '' } }), false);
    assert.equal(fixture.shouldBlock({ currentLocation: { pathname: '/edit/' },
        nextLocation: { pathname: '/lesson/' } }), true);
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Сохранить').props.onClick());
    assert.deepEqual(patches, [{ url: '/blocks/theory/', payload: { type: 'TEXT', content: { html: '<p>Updated theory</p>' } } }]);
    assert.deepEqual(blocks.slice(1), untouched);
    assert.equal(buttons(renderer).find(node => node.children.join('') === 'Сохранить').props.disabled, true);
    await act(async () => buttons(renderer).find(node => node.children.join('').includes('Предпросмотр')).props.onClick());
    assert.equal(fixture.navigate.mock.calls[0].arguments[0], '/lesson/lesson/#block-theory');
});

test('full lesson editor still renders every block and lesson controls', async t => {
    fixture.search = '';
    const renderer = await mount(t);
    assert.equal(cards(renderer).length, 4);
    assert.equal(renderer.root.findAll(node => node.props['data-editable']).length, 1);
    assert.ok(buttons(renderer).some(node => node.children.join('') === 'Удалить'));
});

test('unknown block target is ignored and the full editor remains available', async t => {
    fixture.search = '?block=missing';
    const renderer = await mount(t);
    assert.equal(cards(renderer).length, 4);
    assert.equal(fixture.search, '');
    assert.ok(!JSON.stringify(renderer.toJSON()).includes('Блок не найден'));
});

test('consuming the scroll target preserves drafts and does not restart the editor', async t => {
    fixture.search = '?block=quiz';
    const renderer = await mount(t);
    await act(async () => cards(renderer)[0].findByType('textarea').props.onChange({ target: { value: 'Unsaved theory' } }));
    await act(async () => renderer.update(React.createElement(LessonEditor)));
    assert.equal(cards(renderer).length, 4);
    assert.equal(cards(renderer)[0].findByType('textarea').props.value, 'Unsaved theory');
    assert.equal(window.scrollTo.mock.calls.length, 1);
});

test('dirty markers jump to their block and disappear after saving', async t => {
    const focus = t.mock.fn();
    const scrollIntoView = t.mock.fn();
    document.getElementById = id => id === 'edit-block-theory'
        ? { getBoundingClientRect: () => ({ top: 1000 }), focus, scrollIntoView } : null;
    const renderer = await mount(t);
    const markers = () => buttons(renderer).filter(node => node.props.className === 'unsaved-block-markers__marker');
    assert.equal(markers().length, 0);
    await act(async () => cards(renderer)[0].findByType('textarea').props.onChange({ target: { value: '<p>Unsaved</p>' } }));
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
    await act(async () => cards(renderer)[0].findByType('textarea').props.onChange({ target: { value: '<p>Unsaved</p>' } }));
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Сохранить').props.onClick());
    assert.equal(markers().length, 1);
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Отменить изменения').props.onClick());
    assert.equal(markers().length, 0);
});

test('dropping a block far down saves one move and preserves its unsaved draft', async t => {
    fixture.search = '';
    const renderer = await mount(t);
    await act(async () => renderer.root.findAllByType('textarea')[0].props.onChange({ target: { value: '<p>Unsaved theory</p>' } }));
    const source = cards(renderer)[0].findAllByType('button').find(node => node.props.draggable);
    const dataTransfer = { setData() {}, setDragImage() {} };
    await act(async () => source.props.onDragStart({ clientY: 200, dataTransfer, currentTarget: { closest: () => null } }));
    const destination = cards(renderer).at(-1);
    await act(async () => destination.props.onDrop({ clientY: 95, dataTransfer, preventDefault() {}, stopPropagation() {},
        currentTarget: { getBoundingClientRect: () => ({ top: 0, height: 100 }) } }));
    assert.equal(fixture.post.mock.calls.length, 1);
    assert.deepEqual(fixture.post.mock.calls[0].arguments, ['/blocks/theory/reorder/', { new_order: 4 }]);
    assert.deepEqual(cards(renderer).map(card => card.props.id), ['edit-block-quiz', 'edit-block-code', 'edit-block-fill', 'edit-block-theory']);
    assert.equal(cards(renderer).at(-1).findByType('textarea').props.value, '<p>Unsaved theory</p>');
    assert.equal(cards(renderer).at(-1).findAllByType('button').find(node => node.children.join('') === 'Сохранить').props.disabled, false);
    assert.equal(patches.length, 0);
});

test('block arrows use one atomic reorder request too', async t => {
    fixture.search = '';
    const renderer = await mount(t);
    await act(async () => cards(renderer)[0].findAllByType('button').find(node => node.props.title === 'Вниз').props.onClick());
    assert.deepEqual(fixture.post.mock.calls[0].arguments, ['/blocks/theory/reorder/', { new_order: 2 }]);
    assert.equal(patches.length, 0);
});

test('drop positions account for removing the source and ignore unchanged drops', () => {
    const ids = Array.from({ length: 50 }, (_, i) => String(i));
    assert.equal(dropPosition(ids, '0', '14', true), 15);
    assert.equal(dropPosition(ids, '49', '0', false), 1);
    assert.equal(dropPosition(ids, '0', '1', false), null);
    assert.equal(dropPosition(ids, '1', '0', true), null);
    assert.equal(dropPosition(ids, '1', '1', true), null);
    assert.equal(dropPosition(ids, 'unknown', '2', true), null);
});

test('drag scrolls near the viewport edge and cancellation sends no request', async t => {
    fixture.search = '';
    window.scrollBy = t.mock.fn();
    const renderer = await mount(t);
    const source = cards(renderer)[0].findAllByType('button').find(node => node.props.draggable);
    await act(async () => source.props.onDragStart({ clientY: 790,
        dataTransfer: { setData() {}, setDragImage() {} }, currentTarget: { closest: () => null } }));
    await act(async () => fixture.frame(0));
    assert.ok(window.scrollBy.mock.calls[0].arguments[1] > 0);
    await act(async () => source.props.onDragEnd());
    assert.equal(fixture.post.mock.calls.length, 0);
    assert.ok(cards(renderer).every(card => !card.props.className.includes('--dragging')));
});

test('restoring replaces only its own draft and uses the current saved revision', async t => {
    fixture.search = '';
    window.confirm = () => true;
    blocks[0].updated_at = '2026-11-02T12:00:00Z';
    fixture.post = t.mock.fn(async (url, payload) => {
        assert.equal(url, '/blocks/theory/restore/');
        assert.deepEqual(payload, { revision_id: 42, side: 'before', expected_updated_at: '2026-11-02T12:00:00Z' });
        blocks[0].content = { html: '<p>Restored</p>' };
        return { data: structuredClone(blocks[0]) };
    });
    const renderer = await mount(t);
    await act(async () => cards(renderer)[0].findByType('textarea').props.onChange({ target: { value: 'Unsaved theory' } }));
    await act(async () => cards(renderer)[1].findByType('textarea').props.onChange({ target: { value: 'Unsaved quiz' } }));
    const cardComponent = renderer.root.findAll(node => node.props.draft?.id === 'theory' && node.props.actions)[0];
    await act(async () => cardComponent.props.actions.restore('theory', 42, 'before'));
    assert.equal(cards(renderer)[0].findByType('textarea').props.value, '<p>Restored</p>');
    assert.equal(cards(renderer)[0].findAllByType('button').find(node => node.children.join('') === 'Сохранить').props.disabled, true);
    assert.equal(cards(renderer)[1].findByType('textarea').props.value, 'Unsaved quiz');
});

test('editor badges count each task type independently and update after reordering', async t => {
    blocks.push({ ...structuredClone(blocks[1]), id: 'quiz-2', order_index: 5 });
    blocks.push({ ...structuredClone(blocks[2]), id: 'code-2', order_index: 6 });
    const renderer = await mount(t);
    const labels = () => cards(renderer).map(card => card.findAllByType('span')[0].children.join(''));
    assert.deepEqual(labels(), ['📝 Теория', '❓ Тест 1', '💻 Задача с кодом 1', '✍️ Заполнить пропуски 1', '❓ Тест 2', '💻 Задача с кодом 2']);
    const cardComponent = renderer.root.findAll(node => node.props.draft?.id === 'quiz-2' && node.props.actions)[0];
    await act(async () => cardComponent.props.actions.move('quiz-2', -1));
    await act(async () => cardComponent.props.actions.move('quiz-2', -1));
    await act(async () => cardComponent.props.actions.move('quiz-2', -1));
    const quizCards = cards(renderer).filter(card => ['edit-block-quiz', 'edit-block-quiz-2'].includes(card.props.id));
    assert.deepEqual(quizCards.map(card => card.props.id), ['edit-block-quiz-2', 'edit-block-quiz']);
    assert.deepEqual(quizCards.map(card => card.findAllByType('span')[0].children.join('')), ['❓ Тест 1', '❓ Тест 2']);
});

test('numbering follows new drafts and changes of block type', async t => {
    blocks.push({ ...structuredClone(blocks[1]), id: 'quiz-2', order_index: 5 });
    const renderer = await mount(t);
    await act(async () => buttons(renderer).find(node => node.children.join('') === '❓ Тест').props.onClick());
    const newCard = renderer.root.findAll(node => node.type === 'div' && node.props.id?.startsWith('edit-new-'))[0];
    assert.equal(newCard.findAllByType('span')[0].children.join(''), 'Новый блок: ❓ Тест 3');
    window.confirm = () => true;
    const cardComponent = renderer.root.findAll(node => node.props.draft?.id === 'quiz-2' && node.props.actions)[0];
    await act(async () => cardComponent.props.actions.changeType('quiz-2', 'CODE'));
    const changedCard = cards(renderer).find(card => card.props.id === 'edit-block-quiz-2');
    assert.equal(changedCard.findAllByType('span')[0].children.join(''), '💻 Задача с кодом 2');
    assert.equal(newCard.findAllByType('span')[0].children.join(''), 'Новый блок: ❓ Тест 2');
});

test('sorting editor adds items, orders them, configures both comments and saves through the normal block API', async t => {
    blocks.push({ id: 'sort', type: 'SORT', order_index: 5,
        content: { prompt: '<p>Sort ascending, top to bottom</p>', items: [], html: false } });
    const renderer = await mount(t);
    const card = cards(renderer).find(node => node.props.id === 'edit-block-sort');
    const button = label => card.findAllByType('button').find(node => node.children.join('') === label);
    await act(async () => card.findAllByType('textarea')[0].props.onChange({ target: { value: '<p>Sort ascending from top to bottom</p>' } }));
    await act(async () => button('Сохранить').props.onClick());
    assert.equal(patches.length, 0);
    assert.match(JSON.stringify(renderer.toJSON()), /Добавьте минимум два непустых элемента/);
    await act(async () => button('+ Добавить элемент').props.onClick());
    await act(async () => button('+ Добавить элемент').props.onClick());
    await act(async () => card.findByProps({ 'aria-label': 'Элемент 1' }).props.onChange({ target: { value: 'second' } }));
    await act(async () => card.findByProps({ 'aria-label': 'Элемент 2' }).props.onChange({ target: { value: 'first' } }));
    await act(async () => card.findByProps({ 'aria-label': 'Элемент 2: вверх' }).props.onClick());
    const comments = card.findAllByType('textarea').filter(node => node.props.placeholder === 'Необязательно');
    await act(async () => comments[0].props.onChange({ target: { value: 'Well done' } }));
    await act(async () => comments[1].props.onChange({ target: { value: 'Try again' } }));
    await act(async () => button('Сохранить').props.onClick());
    assert.equal(patches.length, 1);
    assert.equal(patches[0].payload.type, 'SORT');
    assert.deepEqual(patches[0].payload.content.items.map(item => item.text), ['first', 'second']);
    assert.notEqual(patches[0].payload.content.items[0].id, patches[0].payload.content.items[1].id);
    assert.equal(patches[0].payload.content.feedback_correct, 'Well done');
    assert.equal(patches[0].payload.content.feedback_incorrect, 'Try again');
});

test('matching editor creates correct pairs, preserves blanks and first-column settings, and saves comments', async t => {
    blocks.push({ id: 'match', type: 'MATCH', order_index: 5,
        content: { prompt: '<p>Match countries and capitals</p>', pairs: [], html: false, keep_left_order: false } });
    const renderer = await mount(t);
    const card = cards(renderer).find(node => node.props.id === 'edit-block-match');
    const button = label => card.findAllByType('button').find(node => node.children.join('') === label);
    await act(async () => button('+ Добавить пару').props.onClick());
    await act(async () => button('+ Добавить пару').props.onClick());
    await act(async () => button('Сохранить').props.onClick());
    assert.equal(patches.length, 0);
    assert.match(JSON.stringify(renderer.toJSON()), /В каждой строке заполните хотя бы одну ячейку/);
    const change = async (label, value) => act(async () => card.findByProps({ 'aria-label': label }).props.onChange({ target: { value } }));
    await change('Строка 1, первый столбец', 'Bulgaria');
    await change('Строка 1, второй столбец', 'Sofia');
    await change('Строка 2, первый столбец', 'Unmatched country');
    await act(async () => card.findAllByType('input').find(node => node.props.type === 'checkbox').props.onChange({ target: { checked: true } }));
    await act(async () => card.findByProps({ 'aria-label': 'Пара 2: вверх' }).props.onClick());
    const comments = card.findAllByType('textarea').filter(node => node.props.placeholder === 'Необязательно');
    await act(async () => comments[0].props.onChange({ target: { value: 'Correct pairs' } }));
    await act(async () => comments[1].props.onChange({ target: { value: 'Check the capitals' } }));
    await act(async () => button('Сохранить').props.onClick());
    assert.equal(patches.length, 1);
    const { content, type } = patches[0].payload;
    assert.equal(type, 'MATCH');
    assert.equal(content.keep_left_order, true);
    assert.deepEqual(content.pairs.map(row => [row.left.text, row.right.text]), [['Unmatched country', ''], ['Bulgaria', 'Sofia']]);
    const ids = content.pairs.flatMap(row => [row.left.id, row.right.id]);
    assert.equal(new Set(ids).size, 4);
    assert.equal(content.feedback_correct, 'Correct pairs');
    assert.equal(content.feedback_incorrect, 'Check the capitals');
});

test('table editor adds named axes, requires a radio answer for each row, and saves settings and comments', async t => {
    blocks.push({ id: 'table', type: 'TABLE', order_index: 5,
        content: { prompt: '<p>Select languages</p>', rows: [], columns: [], correct_cells: {}, multiple_answers: false,
            shuffle_rows: false, shuffle_columns: false, any_answer_correct: false } });
    const renderer = await mount(t);
    const card = cards(renderer).find(node => node.props.id === 'edit-block-table');
    const button = text => card.findAllByType('button').find(node => node.children.join('') === text);
    for (const label of ['+ Добавить строку', '+ Добавить строку', '+ Добавить столбец', '+ Добавить столбец'])
        await act(async () => button(label).props.onClick());
    for (const [label, value] of [['Название строки 1', 'Australia'], ['Название строки 2', 'Austria'],
        ['Название столбца 1', 'English'], ['Название столбца 2', 'German']]) {
        await act(async () => card.findByProps({ 'aria-label': label }).props.onChange({ target: { value } }));
    }
    await act(async () => button('Сохранить').props.onClick());
    assert.equal(patches.length, 0);
    assert.match(JSON.stringify(renderer.toJSON()), /Отметьте один правильный вариант в каждой строке/);
    for (const label of ['Australia — English', 'Austria — German'])
        await act(async () => card.findByProps({ 'aria-label': label }).props.onChange({ target: { checked: true } }));
    for (const setting of ['Перемешивать порядок строк', 'Перемешивать порядок столбцов']) {
        const label = card.findAllByType('label').find(node => node.children.filter(child => typeof child === 'string').join('').includes(setting));
        await act(async () => label.findByType('input').props.onChange({ target: { checked: true } }));
    }
    const comments = card.findAllByType('textarea').filter(node => node.props.placeholder === 'Необязательно');
    await act(async () => comments[0].props.onChange({ target: { value: 'Correct cells' } }));
    await act(async () => comments[1].props.onChange({ target: { value: 'Adjust the cells' } }));
    await act(async () => button('Сохранить').props.onClick());
    assert.equal(patches.length, 1);
    const { type, content } = patches[0].payload;
    assert.equal(type, 'TABLE');
    assert.deepEqual(content.rows.map(row => row.text), ['Australia', 'Austria']);
    assert.deepEqual(content.columns.map(column => column.text), ['English', 'German']);
    assert.deepEqual(content.correct_cells, { [content.rows[0].id]: [content.columns[0].id], [content.rows[1].id]: [content.columns[1].id] });
    assert.equal(content.shuffle_rows, true);
    assert.equal(content.shuffle_columns, true);
    assert.equal(content.feedback_correct, 'Correct cells');
    assert.equal(content.feedback_incorrect, 'Adjust the cells');
});

test('table editor cleans deleted column references and permits surveys with no answer key', async t => {
    blocks.push({ id: 'table', type: 'TABLE', order_index: 5, content: {
        prompt: 'Survey', rows: [{ id: 'r1', text: 'New' }, { id: 'r2', text: 'Useful' }],
        columns: [{ id: 'c1', text: 'Low' }, { id: 'c2', text: 'High' }], multiple_answers: true,
        correct_cells: { r1: ['c1', 'c2'], r2: ['c1'] }, any_answer_correct: false,
    } });
    const renderer = await mount(t);
    const card = cards(renderer).find(node => node.props.id === 'edit-block-table');
    await act(async () => card.findByProps({ 'aria-label': 'Удалить столбец 1' }).props.onClick());
    const setting = card.findAllByType('label').find(node => node.children.filter(child => typeof child === 'string').join('').includes('Любой ответ верный'));
    await act(async () => setting.findByType('input').props.onChange({ target: { checked: true } }));
    await act(async () => card.findAllByType('button').find(node => node.children.join('') === 'Сохранить').props.onClick());
    assert.deepEqual(patches[0].payload.content.correct_cells, { r1: ['c2'], r2: [] });
    assert.equal(patches[0].payload.content.any_answer_correct, true);
    assert.deepEqual(patches[0].payload.content.columns, [{ id: 'c2', text: 'High' }]);
});

const moveButton = card => card.findAllByType('button').find(node => node.children.join('') === '↗ В другой урок');
const moveForm = card => card.findByProps({ 'aria-label': 'Перенос блока в другой урок' });
const chooseDestination = async card => act(async () => card.findByProps({ 'aria-label': 'Урок назначения' }).props.onChange({ target: { value: 'variables' } }));

test('moving an existing block removes it from the source, preserves other drafts and links to the destination', async t => {
    const renderer = await mount(t);
    const theory = cards(renderer)[0];
    await act(async () => cards(renderer)[1].findByType('textarea').props.onChange({ target: { value: 'Unsaved quiz' } }));
    const insertion = renderer.root.findAll(node => node.props.onPick && node.props.onCancel)[0];
    await act(async () => insertion.props.onPick('TEXT'));
    const newCard = renderer.root.findAll(node => node.type === 'div' && node.props.id?.startsWith('edit-new-'))[0];
    assert.equal(newCard.props.inert, undefined);
    await act(async () => newCard.findByType('textarea').props.onChange({ target: { value: 'New draft' } }));
    await act(async () => moveButton(theory).props.onClick());
    const options = theory.findByProps({ 'aria-label': 'Урок назначения' }).findAllByType('option');
    assert.deepEqual(options.map(node => node.props.value), ['', 'variables']);
    await chooseDestination(theory);
    fixture.post = t.mock.fn(async (url, payload) => {
        assert.equal(url, '/blocks/theory/move/');
        assert.deepEqual(payload, { lesson: 'variables', expected_lesson: 'lesson' });
        const index = blocks.findIndex(block => block.id === 'theory');
        const [block] = blocks.splice(index, 1);
        return { data: { ...block, lesson: 'variables', lesson_title: 'Variables', order_index: 9 } };
    });
    await act(async () => moveForm(theory).props.onSubmit({ preventDefault() {} }));
    assert.deepEqual(cards(renderer).map(card => card.props.id), ['edit-block-quiz', 'edit-block-code', 'edit-block-fill']);
    assert.equal(cards(renderer)[0].findByType('textarea').props.value, 'Unsaved quiz');
    const remaining = renderer.root.findAll(node => node.type === 'div' && node.props.id?.startsWith('edit-new-'))[0];
    assert.equal(remaining.findByType('textarea').props.value, 'New draft');
    const newDraft = renderer.root.findAll(node => node.props.draft?.id === null && node.props.actions)[0].props.draft;
    assert.equal(newDraft.insertBefore, null);
    await act(async () => buttons(renderer).find(node => node.children.join('') === 'Открыть блок').props.onClick());
    assert.deepEqual(fixture.navigate.mock.calls[0].arguments, ['/lesson/variables/edit/?block=theory']);
});

test('moving requires the block draft to be saved first', async t => {
    const renderer = await mount(t);
    const card = cards(renderer)[0];
    await act(async () => card.findByType('textarea').props.onChange({ target: { value: 'Unsaved theory' } }));
    assert.equal(moveButton(card).props.disabled, true);
    assert.match(moveButton(card).props.title, /Сохраните/);
    await act(async () => card.findAllByType('button').find(node => node.children.join('') === 'Сохранить').props.onClick());
    assert.equal(moveButton(card).props.disabled, false);
});

test('move failure keeps the block and destination selection and allows a retry', async t => {
    const renderer = await mount(t);
    const card = cards(renderer)[0];
    await act(async () => moveButton(card).props.onClick());
    await chooseDestination(card);
    fixture.post = async () => { throw { response: { data: { detail: 'Block changed. Reload.' } } }; };
    await act(async () => moveForm(card).props.onSubmit({ preventDefault() {} }));
    assert.equal(cards(renderer).length, 4);
    assert.match(JSON.stringify(renderer.toJSON()), /Block changed. Reload./);
    assert.equal(card.findByProps({ 'aria-label': 'Урок назначения' }).props.value, 'variables');
    assert.equal(moveForm(card).findAllByType('button').find(node => node.props.type === 'submit').props.disabled, false);
    assert.equal(card.props.inert, undefined);
});

test('lesson loading errors can retry and a course with no destination explains why', async t => {
    const renderer = await mount(t);
    const card = cards(renderer)[0];
    const get = fixture.get;
    fixture.get = async url => {
        if (url === '/lessons/outline/') throw Error('Offline');
        return get(url);
    };
    await act(async () => moveButton(card).props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()), /Не удалось загрузить уроки/);
    fixture.get = async url => url === '/lessons/outline/' ? { data: [{ id: 'lesson', title: 'Current', position: 1 }] } : get(url);
    await act(async () => moveForm(card).findAllByType('button').find(node => node.children.join('') === 'Повторить загрузку').props.onClick());
    assert.match(JSON.stringify(renderer.toJSON()), /В этом курсе пока нет других уроков/);
    await act(async () => moveForm(card).findAllByType('button').find(node => node.children.join('') === 'Отмена').props.onClick());
    assert.equal(moveButton(card).props.disabled, false);
    assert.equal(fixture.post.mock.calls.length, 0);
});

test('pending moves freeze the moved editor and prevent duplicate submissions', async t => {
    const renderer = await mount(t);
    const card = cards(renderer)[0];
    await act(async () => moveButton(card).props.onClick());
    await chooseDestination(card);
    let finish;
    fixture.post = t.mock.fn(() => new Promise(resolve => { finish = resolve; }));
    let pending;
    await act(async () => { pending = moveForm(card).props.onSubmit({ preventDefault() {} }); });
    assert.equal(card.props.inert, true);
    assert.equal(card.props['aria-busy'], true);
    assert.equal(moveForm(card).findAllByType('button').find(node => node.props.type === 'submit').props.disabled, true);
    await act(async () => { await moveForm(card).props.onSubmit({ preventDefault() {} }); });
    assert.equal(fixture.post.mock.calls.length, 1);
    await act(async () => {
        finish({ data: { id: 'theory', lesson: 'variables', lesson_title: 'Variables' } });
        await pending;
    });
    assert.equal(cards(renderer).length, 3);
});
