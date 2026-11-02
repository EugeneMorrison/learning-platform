import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const server = await createServer({
    configFile: false,
    ssr: { noExternal: ['react-router-dom'] },
    server: { middlewareMode: true, hmr: false },
    plugins: [{ name: 'floating-navigation-test-router', enforce: 'pre',
        resolveId(source) { if (source === 'react-router-dom') return '\0floating-router'; },
        load(id) {
            if (id === '\0floating-router') return `import React from 'react';
                export const Link = props => React.createElement('a', { href: props.to, onClick: props.onClick }, props.children);`;
        },
    }],
});
const { default: FloatingLessonNav } = await server.ssrLoadModule('/src/components/FloatingLessonNav.jsx');
after(() => server.close());

let topNode, bottomNode, observers, resize, headerHeight;
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    topNode = {};
    bottomNode = {};
    observers = [];
    headerHeight = 72;
    globalThis.document = { querySelector: () => ({ getBoundingClientRect: () => ({ bottom: headerHeight }) }) };
    globalThis.window = { addEventListener() {}, removeEventListener() {}, scrollTo: t.mock.fn() };
    globalThis.IntersectionObserver = class {
        constructor(callback, options) {
            this.notify = callback;
            this.options = options;
            this.targets = [];
            this.disconnected = false;
            observers.push(this);
        }
        observe(node) { this.targets.push(node); }
        disconnect() { this.disconnected = true; }
    };
    globalThis.ResizeObserver = class {
        constructor(callback) { resize = callback; }
        observe() {}
        disconnect() {}
    };
    t.mock.method(console, 'error', () => {});
});

async function mount(t, props = {}) {
    let renderer;
    await act(async () => { renderer = create(React.createElement(FloatingLessonNav, {
        previousLessonId: 'previous', nextLessonId: 'next', topRef: { current: topNode }, bottomRef: { current: bottomNode }, ...props,
    })); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}
async function visibility(top, bottom) {
    await act(async () => observers.at(-1).notify([
        { target: topNode, isIntersecting: top }, { target: bottomNode, isIntersecting: bottom },
    ]));
}

test('floating navigation appears only when both original rows are off-screen', async t => {
    const renderer = await mount(t);
    assert.equal(renderer.toJSON(), null);
    assert.deepEqual(observers[0].targets, [topNode, bottomNode]);
    assert.equal(observers[0].options.rootMargin, '-72px 0px 0px 0px');
    await visibility(true, false);
    assert.equal(renderer.toJSON(), null);
    await visibility(false, false);
    assert.deepEqual(renderer.root.findAllByType('a').map(node => node.props.href), ['/lesson/previous/', '/lesson/next/']);
    await visibility(false, true);
    assert.equal(renderer.toJSON(), null);
    await visibility(false, false);
    assert.equal(renderer.root.findAllByType('a').length, 2);
    await visibility(true, false);
    assert.equal(renderer.toJSON(), null);
});

test('editor links open editors and leave scroll and unsaved-change handling to the router', async t => {
    const renderer = await mount(t, { editor: true });
    await visibility(false, false);
    const links = renderer.root.findAllByType('a');
    assert.deepEqual(links.map(node => node.props.href), ['/lesson/previous/edit/', '/lesson/next/edit/']);
    assert.ok(links.every(node => node.props.onClick === undefined));
    assert.equal(window.scrollTo.mock.calls.length, 0);
});

test('first and last lessons only offer existing neighbours; a single lesson has no bar', async t => {
    const first = await mount(t, { previousLessonId: null });
    await visibility(false, false);
    assert.deepEqual(first.root.findAllByType('a').map(node => node.props.href), ['/lesson/next/']);
    const last = await mount(t, { nextLessonId: null });
    await visibility(false, false);
    assert.deepEqual(last.root.findAllByType('a').map(node => node.props.href), ['/lesson/previous/']);
    const count = observers.length;
    const only = await mount(t, { previousLessonId: null, nextLessonId: null });
    assert.equal(only.toJSON(), null);
    assert.equal(observers.length, count);
});

test('floating row follows header size changes and releases observers on unmount', async t => {
    const renderer = await mount(t);
    await visibility(false, false);
    assert.equal(renderer.root.findByType('nav').props.style.top, 80);
    headerHeight = 112;
    await act(async () => resize());
    await visibility(false, false);
    assert.equal(observers[0].disconnected, true);
    assert.equal(renderer.root.findByType('nav').props.style.top, 120);
    await act(async () => renderer.unmount());
    assert.equal(observers.at(-1).disconnected, true);
});

test('scrolling never removes a floating link while it has keyboard focus', async t => {
    const renderer = await mount(t);
    await visibility(false, false);
    await act(async () => renderer.root.findByType('nav').props.onFocus());
    await visibility(false, true);
    assert.equal(renderer.root.findAllByType('a').length, 2);
    await act(async () => renderer.root.findByType('nav').props.onBlur({ currentTarget: { contains: () => false }, relatedTarget: null }));
    assert.equal(renderer.toJSON(), null);
});

test('editor preview shares the next-lesson column and preserves the saved-block anchor', async t => {
    const renderer = await mount(t, { editor: true, previewTo: '/lesson/current/#block-saved' });
    await visibility(false, false);
    const previous = renderer.root.findByProps({ className: 'floating-lesson-nav__side floating-lesson-nav__previous' });
    const next = renderer.root.findByProps({ className: 'floating-lesson-nav__side floating-lesson-nav__next' });
    assert.deepEqual(previous.findAllByType('a').map(node => node.props.href), ['/lesson/previous/edit/']);
    assert.deepEqual(next.findAllByType('a').map(node => node.props.href), ['/lesson/current/#block-saved', '/lesson/next/edit/']);
    assert.ok(next.findAllByType('a')[0].children.join('').includes('Предпросмотр'));
    assert.equal(next.findAllByType('a')[0].props.onClick, undefined);
    assert.ok(renderer.root.findByType('nav').props.className.includes('floating-lesson-nav--editor'));
});

test('preview remains available on the last lesson and is absent from the regular view', async t => {
    const last = await mount(t, { editor: true, nextLessonId: null, previewTo: '/lesson/current/' });
    await visibility(false, false);
    assert.deepEqual(last.root.findAllByType('a').map(node => node.props.href), ['/lesson/previous/edit/', '/lesson/current/']);
    const regular = await mount(t, { previewTo: '/lesson/current/' });
    await visibility(false, false);
    assert.deepEqual(regular.root.findAllByType('a').map(node => node.props.href), ['/lesson/previous/', '/lesson/next/']);
});
