import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__courseReorderTest = {};
const server = await createServer({
    configFile: false,
    ssr: { noExternal: ['react-router-dom'] },
    server: { middlewareMode: true, hmr: false },
    plugins: [{
        name: 'course-reorder-test-boundaries', enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0course-api';
            if (source === 'react-router-dom') return '\0course-router';
            if (source === '../lib/notifications') return '\0course-notifications';
            if (source === '../lib/chatSocket') return '\0course-socket';
            if (source.startsWith('../components/') && !source.endsWith('/DragHandle')) return '\0course-decoration';
        },
        load(id) {
            if (id === '\0course-api') return `export default {
                get: (...args) => globalThis.__courseReorderTest.get(...args),
                post: (...args) => globalThis.__courseReorderTest.post(...args),
                delete: (...args) => globalThis.__courseReorderTest.delete(...args),
            };`;
            if (id === '\0course-router') return `import React from 'react';
                export const useParams = () => ({ courseId: 'course' });
                export const useNavigate = () => () => {};
                export const useSearchParams = () => [new URLSearchParams(), () => {}];
                export const Link = props => React.createElement('a', { href: props.to }, props.children);
            `;
            if (id === '\0course-notifications') return `
                export const badgeText = () => '';
                export const useActiveChat = () => {};
                export const useNotifications = () => ({ conversations: [], markRead() {}, unreadFor: () => 0 });
            `;
            if (id === '\0course-socket') return `
                export const MAX_MESSAGE_LENGTH = 2000;
                export const mergeMessages = () => [];
                export const messageLength = text => text.length;
                export const useChatSocket = () => ({});
            `;
            if (id === '\0course-decoration') return `import React from 'react';
                export default props => props.display || null;
                export const TaskProgress = () => null;
            `;
        },
    }],
});
const { default: CoursePage } = await server.ssrLoadModule('/src/pages/CoursePage.jsx');
after(() => server.close());

let lessons;
let outline;
let enrollments;
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = { innerHeight: 800, scrollBy() {}, addEventListener() {}, removeEventListener() {} };
    globalThis.document = { querySelector: () => null, addEventListener() {}, removeEventListener() {} };
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = () => {};
    fixture.userId = 'author';
    lessons = Array.from({ length: 50 }, (_, index) => ({ id: String(index), title: `Lesson ${index + 1}`, order_index: index, block_count: 0 }));
    outline = [];
    enrollments = [];
    fixture.get = async url => {
        if (url === '/auth/me/') return { data: { id: fixture.userId } };
        if (url === '/courses/course/') return { data: { id: 'course', author: 'author', title: 'Course' } };
        if (url === '/lessons/?course=course') return { data: structuredClone(lessons) };
        if (url === '/lessons/outline/') return { data: structuredClone(outline) };
        if (url.endsWith('/enrollments/')) return { data: structuredClone(enrollments) };
        throw Error(`Unexpected request: ${url}`);
    };
    fixture.post = t.mock.fn(async (url, payload) => {
        const index = lessons.findIndex(lesson => url === `/lessons/${lesson.id}/reorder/`);
        const [moved] = lessons.splice(index, 1);
        lessons.splice(payload.new_order - 1, 0, moved);
        return { data: structuredClone(lessons) };
    });
    fixture.delete = t.mock.fn(async () => ({}));
    window.confirm = t.mock.fn(() => true);
    t.mock.method(console, 'error', () => {});
});

async function mount(t) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(CoursePage)); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}
const rows = renderer => renderer.root.findAll(node => node.type === 'div' && node.props.className?.split(' ').includes('lesson-row'));
const stepCounts = row => row.findAllByProps({ className: 'lesson-row__step-count' })
    .map(node => [].concat(node.props.children).join(''));

test('authors see total and nonzero step types matching the syllabus', async t => {
    outline = [{ id: '0', text_count: 1, quiz_count: 12, code_count: 7, fill_count: 1, sort_count: 2, match_count: 3, table_count: 2, task_count: 27, solved_count: 0 }];
    const renderer = await mount(t);
    assert.deepEqual(stepCounts(rows(renderer)[0]), ['Шагов: 28', 'Теория: 1', 'Тесты: 12', 'Задачи: 7', 'Пропуски: 1', 'Сортировка: 2', 'Сопоставление: 3', 'Таблицы: 2']);
    assert.equal(rows(renderer)[0].findByType('a').props.href, '/lesson/0/');
});

test('theory-only and empty lessons are distinguishable, including newly created lessons', async t => {
    outline = [
        { id: '0', text_count: 2, quiz_count: 0, code_count: 0, fill_count: 0, sort_count: 0, match_count: 0, table_count: 0, task_count: 0 },
        { id: '1', text_count: 0, quiz_count: 0, code_count: 0, fill_count: 0, sort_count: 0, match_count: 0, table_count: 0, task_count: 0 },
    ];
    const renderer = await mount(t);
    assert.deepEqual(stepCounts(rows(renderer)[0]), ['Шагов: 2', 'Теория: 2']);
    assert.deepEqual(stepCounts(rows(renderer)[1]), ['Нет шагов']);
    // A newly created lesson is in the lesson list before it has an outline.
    assert.deepEqual(stepCounts(rows(renderer)[2]), ['Нет шагов']);
});

test('unavailable outline does not mislabel an existing lesson as empty', async t => {
    lessons[0].block_count = 5;
    const get = fixture.get;
    fixture.get = url => url === '/lessons/outline/' ? Promise.reject(Error('Offline')) : get(url);
    const renderer = await mount(t);
    assert.deepEqual(stepCounts(rows(renderer)[0]), ['Шагов: 5']);
    assert.equal(rows(renderer)[0].findByProps({ 'aria-label': 'Состав урока' })
        .findByProps({ className: 'lesson-row__hint' }).props.children, 'Состав шагов недоступен');
});

test('author can drag the first of 50 lessons after lesson 15 in one request', async t => {
    outline = [{ id: '0', text_count: 2, quiz_count: 0, code_count: 3, fill_count: 0, sort_count: 0, match_count: 0, table_count: 0, task_count: 3, solved_count: 0 }];
    const renderer = await mount(t);
    assert.equal(rows(renderer).length, 50);
    const handle = rows(renderer)[0].findAllByType('button').find(node => node.props.draggable);
    const dataTransfer = { setData() {}, setDragImage() {} };
    await act(async () => handle.props.onDragStart({ clientY: 200, dataTransfer, currentTarget: { closest: () => null } }));
    await act(async () => rows(renderer)[14].props.onDrop({ clientY: 90, dataTransfer, preventDefault() {}, stopPropagation() {},
        currentTarget: { getBoundingClientRect: () => ({ top: 0, height: 100 }) } }));
    assert.equal(fixture.post.mock.calls.length, 1);
    assert.deepEqual(fixture.post.mock.calls[0].arguments, ['/lessons/0/reorder/', { new_order: 15 }]);
    assert.equal(rows(renderer)[14].findByType('a').props.href, '/lesson/0/');
    assert.deepEqual(stepCounts(rows(renderer)[14]), ['Шагов: 5', 'Теория: 2', 'Задачи: 3']);
    assert.ok(JSON.stringify(renderer.toJSON()).includes('теперь 15-й'));
});

test('students have no drag handles or drop handlers', async t => {
    fixture.userId = 'student';
    enrollments = [{ id: 'enrollment', student: 'student', student_name: 'Alice' }];
    const renderer = await mount(t);
    assert.equal(renderer.root.findAll(node => node.type === 'button' && node.props.draggable).length, 0);
    assert.ok(rows(renderer).every(row => row.props.onDrop === undefined));
    assert.ok(rows(renderer).every(row => stepCounts(row).length === 0));
    assert.equal(renderer.root.findAll(node => node.type === 'button' && node.props.children === 'Удалить из курса').length, 0);
});

const studentRows = renderer => renderer.root.findAll(node => node.type === 'div' && node.props.className === 'card student-row');
const removeButton = renderer => renderer.root.findByProps({ 'aria-label': 'Удалить из курса: Alice' });

test('removing a student confirms course-wide access loss and refreshes lesson statistics', async t => {
    enrollments = [{ id: 'enrollment', student: 'student', student_name: 'Alice' }];
    const renderer = await mount(t);
    let reads = 0;
    const get = fixture.get;
    fixture.get = async (...args) => {
        if (args[0] === '/lessons/outline/') reads++;
        return get(...args);
    };
    await act(async () => removeButton(renderer).props.onClick());
    assert.match(window.confirm.mock.calls[0].arguments[0], /Alice.*Доступ ко всем урокам курса/);
    assert.deepEqual(fixture.delete.mock.calls[0].arguments, ['/courses/course/enrollments/enrollment/']);
    assert.equal(studentRows(renderer).length, 0);
    assert.equal(reads, 1);
});

test('canceling removal leaves the enrollment untouched', async t => {
    enrollments = [{ id: 'enrollment', student: 'student', student_name: 'Alice' }];
    window.confirm = () => false;
    const renderer = await mount(t);
    await act(async () => removeButton(renderer).props.onClick());
    assert.equal(fixture.delete.mock.calls.length, 0);
    assert.equal(studentRows(renderer).length, 1);
});

test('failed removal keeps the student and offers retry with a visible error', async t => {
    enrollments = [{ id: 'enrollment', student: 'student', student_name: 'Alice' }];
    fixture.delete = async () => { throw Error('Offline'); };
    const renderer = await mount(t);
    await act(async () => removeButton(renderer).props.onClick());
    assert.equal(studentRows(renderer).length, 1);
    assert.equal(removeButton(renderer).props.disabled, false);
    assert.match(renderer.root.findByProps({ role: 'alert' }).props.children, /Не удалось удалить/);
});

test('pending removal prevents duplicate requests', async t => {
    enrollments = [{ id: 'enrollment', student: 'student', student_name: 'Alice' }];
    let finish;
    fixture.delete = t.mock.fn(() => new Promise(resolve => { finish = resolve; }));
    const renderer = await mount(t);
    let pending;
    await act(async () => {
        const click = removeButton(renderer).props.onClick;
        pending = click();
        await click();
    });
    assert.equal(fixture.delete.mock.calls.length, 1);
    assert.equal(removeButton(renderer).props.disabled, true);
    await act(async () => { finish({}); await pending; });
    assert.equal(studentRows(renderer).length, 0);
});

test('successful removal remains visible if refreshing statistics fails', async t => {
    enrollments = [{ id: 'enrollment', student: 'student', student_name: 'Alice' }];
    const renderer = await mount(t);
    const get = fixture.get;
    fixture.get = url => url === '/lessons/outline/' ? Promise.reject(Error('Offline')) : get(url);
    await act(async () => removeButton(renderer).props.onClick());
    assert.equal(studentRows(renderer).length, 0);
    assert.match(renderer.root.findByProps({ role: 'alert' }).props.children, /Учащийся удалён.*статистику/);
});

test('failed lesson move keeps the original order and restores the controls', async t => {
    globalThis.alert = t.mock.fn();
    fixture.post = async () => { throw Error('Offline'); };
    const renderer = await mount(t);
    const first = rows(renderer)[0];
    await act(async () => first.findAllByType('button').find(node => node.props.title === 'Переместить ниже').props.onClick());
    assert.equal(rows(renderer)[0].findByType('a').props.href, '/lesson/0/');
    assert.equal(rows(renderer)[0].findAllByType('button').find(node => node.props.draggable).props.disabled, false);
    assert.equal(globalThis.alert.mock.calls.length, 1);
});
