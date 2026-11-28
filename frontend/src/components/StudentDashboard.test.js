import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__dashboardTest = {};
const server = await createServer({
    configFile: false,
    ssr: { noExternal: ['react-router-dom'] },
    server: { middlewareMode: true, hmr: false },
    plugins: [{
        name: 'dashboard-test-boundaries', enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0dashboard-api';
            if (source === 'react-router-dom') return '\0dashboard-router';
        },
        load(id) {
            if (id === '\0dashboard-api') return `export default {
                get: (...args) => globalThis.__dashboardTest.get(...args),
                patch: (...args) => globalThis.__dashboardTest.patch(...args),
            };`;
            if (id === '\0dashboard-router') return `import React from 'react';
                export const Link = props => React.createElement('a', { href: props.to }, props.children);`;
        },
    }],
});
const { default: Dashboard } = await server.ssrLoadModule('/src/components/StudentDashboard.jsx');
const { default: Editor } = await server.ssrLoadModule('/src/components/CourseRecommendationsEditor.jsx');
after(() => server.close());
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    t.mock.method(console, 'error', () => {});
});
async function mount(t, component, props) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(component, props)); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}

test('dashboard renders all three sections with resume, review and public detail links', async t => {
    fixture.get = async () => ({ data: {
        in_progress: [{ id: 'one', title: 'First', cover: null, completion_percentage: 50, last_lesson: 'last' }],
        completed: [{ id: 'two', title: 'Finished', cover: null }],
        recommended: [{ id: 'three', title: 'Next', slug: 'next', level: 'BEGINNER', price: '1250.50', cover: null }],
    } });
    const renderer = await mount(t, Dashboard);
    assert.equal(renderer.root.findAllByType('section').length, 3);
    assert.equal(renderer.root.findByType('progress').props.value, 50);
    assert.deepEqual(renderer.root.findAllByType('a').map(a => a.props.href), [
        '/lesson/last/', '/courses/two/', '/course/next/',
    ]);
});

test('failed loading offers retry, then each empty section has a message', async t => {
    fixture.get = async () => { throw Error('offline'); };
    const renderer = await mount(t, Dashboard);
    assert.equal(renderer.root.findAllByProps({ role: 'alert' }).length, 1);
    fixture.get = async () => ({ data: { in_progress: [], completed: [], recommended: [] } });
    await act(async () => renderer.root.findByType('button').props.onClick());
    assert.equal(renderer.root.findAllByType('section').length, 3);
    assert.equal(renderer.root.findAllByProps({ className: 'muted' }).length, 3);
});

test('author selects follow-ups, saves, and can remove the relationship', async t => {
    fixture.get = async () => ({ data: [{ id: 'one', title: 'Current' }, { id: 'two', title: 'Next', is_published: true }] });
    const saved = [];
    fixture.patch = async (url, body) => {
        assert.equal(url, '/courses/one/');
        saved.push(body.recommended_courses);
        return { data: body };
    };
    const renderer = await mount(t, Editor, { courseId: 'one', value: [], onSaved() {} });
    assert.equal(renderer.root.findAllByType('input').length, 1);
    await act(async () => renderer.root.findByType('input').props.onChange({ target: { checked: true } }));
    await act(async () => renderer.root.findByType('form').props.onSubmit({ preventDefault() {} }));
    await act(async () => renderer.root.findByType('input').props.onChange({ target: { checked: false } }));
    await act(async () => renderer.root.findByType('form').props.onSubmit({ preventDefault() {} }));
    assert.deepEqual(saved, [['two'], []]);
});
