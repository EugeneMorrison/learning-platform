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
                export const useNotifications = () => ({ conversations: [], markRead() {} });
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
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = { innerHeight: 800, scrollBy() {}, addEventListener() {}, removeEventListener() {} };
    globalThis.document = { querySelector: () => null, addEventListener() {}, removeEventListener() {} };
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = () => {};
    fixture.userId = 'author';
    lessons = Array.from({ length: 50 }, (_, index) => ({ id: String(index), title: `Lesson ${index + 1}`, order_index: index }));
    fixture.get = async url => {
        if (url === '/auth/me/') return { data: { id: fixture.userId } };
        if (url === '/courses/course/') return { data: { id: 'course', author: 'author', title: 'Course' } };
        if (url === '/lessons/?course=course') return { data: structuredClone(lessons) };
        if (url === '/lessons/outline/' || url.endsWith('/enrollments/')) return { data: [] };
        throw Error(`Unexpected request: ${url}`);
    };
    fixture.post = t.mock.fn(async (url, payload) => {
        const index = lessons.findIndex(lesson => url === `/lessons/${lesson.id}/reorder/`);
        const [moved] = lessons.splice(index, 1);
        lessons.splice(payload.new_order - 1, 0, moved);
        return { data: structuredClone(lessons) };
    });
    t.mock.method(console, 'error', () => {});
});

async function mount(t) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(CoursePage)); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}
const rows = renderer => renderer.root.findAll(node => node.type === 'div' && node.props.className?.split(' ').includes('lesson-row'));

test('author can drag the first of 50 lessons after lesson 15 in one request', async t => {
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
    assert.ok(JSON.stringify(renderer.toJSON()).includes('теперь 15-й'));
});

test('students have no drag handles or drop handlers', async t => {
    fixture.userId = 'student';
    const renderer = await mount(t);
    assert.equal(renderer.root.findAll(node => node.type === 'button' && node.props.draggable).length, 0);
    assert.ok(rows(renderer).every(row => row.props.onDrop === undefined));
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
