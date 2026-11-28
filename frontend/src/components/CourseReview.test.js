import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__reviewTest = {};
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
                get: (...args) => globalThis.__reviewTest.get(...args),
                put: (...args) => globalThis.__reviewTest.put(...args),
            };`;
            if (id === '\0dashboard-router') return `import React from 'react';
                export const Link = props => React.createElement('a', { href: props.to }, props.children);`;
        },
    }],
});
const { default: ReviewForm } = await server.ssrLoadModule('/src/components/CourseReview.jsx');

after(() => server.close());
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = { dispatchEvent() {} };
    t.mock.method(console, 'error', () => {});
});
async function mount(t, component, props) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(component, props)); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}

test('eligible student submits mandatory stars with optional text and can edit later', async t => {
    fixture.get = async () => ({ data: { eligible: true, review: null } });
    const submissions = [];
    fixture.put = async (url, body) => {
        assert.equal(url, '/courses/course/my-review/');
        submissions.push(body);
        return { data: { ...body, status: 'pending' } };
    };
    const renderer = await mount(t, ReviewForm, { courseId: 'course', congratulations: true });
    assert.equal(renderer.root.findAllByType('input').length, 5);
    assert.equal(renderer.root.findByType('button').props.disabled, true);
    assert.equal(renderer.root.findAllByType('h2').length, 1);
    await act(async () => renderer.root.findAllByType('input')[4].props.onChange());
    await act(async () => renderer.root.findByType('form').props.onSubmit({ preventDefault() {} }));
    assert.deepEqual(submissions, [{ rating: 5, text: '' }]);
    assert.equal(renderer.root.findAllByProps({ role: 'status' }).length, 1);
    await act(async () => renderer.root.findByType('textarea').props.onChange({ target: { value: 'Updated' } }));
    await act(async () => renderer.root.findByType('form').props.onSubmit({ preventDefault() {} }));
    assert.equal(submissions[1].text, 'Updated');
});

test('ineligible student sees no invitation and failures preserve their draft', async t => {
    fixture.get = async () => ({ data: { eligible: false, review: null } });
    const renderer = await mount(t, ReviewForm, { courseId: 'course' });
    assert.equal(renderer.toJSON(), null);
    fixture.get = async () => ({ data: { eligible: true, review: null } });
    await act(async () => renderer.update(React.createElement(ReviewForm, { courseId: 'course', refreshKey: 1 })));
    fixture.put = async () => { throw Error('offline'); };
    await act(async () => renderer.root.findAllByType('input')[1].props.onChange());
    await act(async () => renderer.root.findByType('form').props.onSubmit({ preventDefault() {} }));
    assert.equal(renderer.root.findAllByProps({ role: 'alert' }).length, 1);
    assert.equal(renderer.root.findAllByType('input')[1].props.checked, true);
});

