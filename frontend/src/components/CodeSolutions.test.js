import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const fixture = globalThis.__codeSolutionsTest = {};
const server = await createServer({ configFile: false, server: { middlewareMode: true, hmr: false },
    plugins: [{ name: 'solutions-api', enforce: 'pre',
        resolveId: source => source === '../api' ? '\0solutions-api' : undefined,
        load: id => id === '\0solutions-api'
            ? 'export default { get: (...args) => globalThis.__codeSolutionsTest.get(...args) };' : undefined,
    }],
});
const { default: CodeSolutions } = await server.ssrLoadModule('/src/components/CodeSolutions.jsx');
after(() => server.close());

const empty = { official_solution: null, results: [], next_offset: null };
const peer = { id: 'peer-1', author_name: 'Ada', code: 'if True:\n    print("<script>alert(1)</script>")\n' };
const official = { author_name: 'Author', code: 'print(1)\n' };
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    t.mock.method(console, 'error', () => {});
    fixture.get = t.mock.fn(async () => ({ data: empty }));
});

async function mount(t, props = {}) {
    let page;
    await act(async () => { page = create(React.createElement(CodeSolutions, { blockId: 'code-task', unlocked: true, ...props })); });
    t.after(async () => { await act(async () => page.unmount()); });
    return page;
}
const button = (page, label) => page.root.findAllByType('button').find(node => node.children.join('') === label);
const click = (page, label) => act(async () => button(page, label).props.onClick());
const codes = page => page.root.findAllByType('code').map(node => node.children.join(''));

test('locked tasks do not fetch or render solutions', async t => {
    const page = await mount(t, { unlocked: false });
    assert.equal(button(page, 'Посмотреть другие решения').props.disabled, true);
    assert.equal(fixture.get.mock.calls.length, 0);
    assert.deepEqual(codes(page), []);
});

test('loads lazily, puts the official solution first and renders code safely with exact whitespace', async t => {
    fixture.get = t.mock.fn(async () => ({ data: { ...empty, official_solution: official, results: [peer] } }));
    const page = await mount(t);
    assert.equal(fixture.get.mock.calls.length, 0);
    await click(page, 'Посмотреть другие решения');
    assert.deepEqual(fixture.get.mock.calls[0].arguments, ['/blocks/code-task/solutions/', { params: { offset: 0 } }]);
    assert.deepEqual(codes(page), [official.code, peer.code]);
    assert.deepEqual(page.root.findAllByType('h4').map(node => node.children.join('')), [
        'Официальное решение · Author', 'Решение ученика · Ada',
    ]);
    assert.equal(page.root.findAll(node => node.props.dangerouslySetInnerHTML != null).length, 0);
    assert.equal(button(page, 'Скрыть другие решения').props['aria-expanded'], true);
    await click(page, 'Скрыть другие решения');
    assert.deepEqual(codes(page), []);
});

test('handles an empty list and solutions without an official answer', async t => {
    const page = await mount(t);
    await click(page, 'Посмотреть другие решения');
    assert.ok(JSON.stringify(page.toJSON()).includes('Других решений пока нет.'));
    await click(page, 'Скрыть другие решения');
    fixture.get = async () => ({ data: { ...empty, results: [peer] } });
    await click(page, 'Посмотреть другие решения');
    assert.deepEqual(codes(page), [peer.code]);
    assert.equal(button(page, 'Показать ещё решения'), undefined);
});

test('failed pagination keeps loaded code and retries the same page without duplication', async t => {
    fixture.get = t.mock.fn(async () => ({ data: { ...empty, official_solution: official, results: [peer], next_offset: 10 } }));
    const page = await mount(t);
    await click(page, 'Посмотреть другие решения');
    fixture.get = t.mock.fn(async () => { throw Error('Offline'); });
    await click(page, 'Показать ещё решения');
    assert.deepEqual(codes(page), [official.code, peer.code]);
    assert.equal(page.root.findAllByProps({ role: 'alert' }).length, 1);
    fixture.get = t.mock.fn(async () => ({ data: { ...empty, official_solution: official,
        results: [{ ...peer, id: 'peer-2', code: 'print(2)' }] } }));
    await click(page, 'Повторить');
    assert.deepEqual(fixture.get.mock.calls[0].arguments, ['/blocks/code-task/solutions/', { params: { offset: 10 } }]);
    assert.deepEqual(codes(page), [official.code, peer.code, 'print(2)']);
    assert.equal(page.root.findAllByProps({ role: 'alert' }).length, 0);
    assert.equal(button(page, 'Показать ещё решения'), undefined);
});

test('server access denial is shown and can be retried after access is restored', async t => {
    fixture.get = async () => { throw { response: { data: { detail: 'Сначала решите задачу.' } } }; };
    const page = await mount(t);
    await click(page, 'Посмотреть другие решения');
    assert.ok(JSON.stringify(page.toJSON()).includes('Сначала решите задачу.'));
    assert.deepEqual(codes(page), []);
    fixture.get = async () => ({ data: { ...empty, official_solution: official } });
    await click(page, 'Повторить');
    assert.deepEqual(codes(page), [official.code]);
});

test('late responses after closing cannot replace a newly opened list', async t => {
    let finish;
    fixture.get = () => new Promise(resolve => { finish = resolve; });
    const page = await mount(t);
    await click(page, 'Посмотреть другие решения');
    assert.equal(page.root.findAllByProps({ role: 'status' }).length, 1);
    await click(page, 'Скрыть другие решения');
    fixture.get = async () => ({ data: empty });
    await click(page, 'Посмотреть другие решения');
    await act(async () => finish({ data: { ...empty, official_solution: official } }));
    assert.deepEqual(codes(page), []);
    assert.ok(JSON.stringify(page.toJSON()).includes('Других решений пока нет.'));
});
