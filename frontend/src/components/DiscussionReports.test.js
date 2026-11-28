import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

const fixture = globalThis.__discussionFeedTest = {};
const server = await createServer({ configFile: false, server: { middlewareMode: true, hmr: false },
    plugins: [{ name: 'discussion-feed-mocks', enforce: 'pre',
        resolveId: source => source === '../api' ? `\0feed:${source}` : undefined,
        load(id) {
            if (id === '\0feed:../api') return 'export default { get: (...args) => globalThis.__discussionFeedTest.get(...args) };';
        },
    }],
});
const { default: DiscussionReports } = await server.ssrLoadModule('/src/components/DiscussionReports.jsx');
after(() => server.close());

const comment = { id: 1, text: 'Question from a student', user_name: 'Student',
    created_at: '2026-11-28T12:00:00Z', is_unread: true,
    block_id: 'task', lesson_id: 'lesson', lesson_title: 'Lesson', course_title: 'Course' };
beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    t.mock.method(console, 'error', () => {});
    globalThis.window = {
        setInterval(callback) { fixture.refresh = callback; return 1; },
        clearInterval() {}, addEventListener() {}, removeEventListener() {},
    };
    fixture.feed = { comments: [], unread_count: 0, next_offset: null };
    fixture.get = t.mock.fn(async url => ({ data: url === '/discussions/comments/' ? fixture.feed
        : url === '/discussions/reports/' ? { reports: [] } : { bans: [] } }));
});
async function mount(t) {
    let page;
    await act(async () => { page = create(React.createElement(MemoryRouter, null, React.createElement(DiscussionReports))); });
    t.after(async () => { await act(async () => page.unmount()); });
    return page;
}
const content = page => JSON.stringify(page.toJSON());

test('empty dashboard uses the requested discussion wording', async t => {
    const page = await mount(t);
    assert.ok(content(page).includes('Обсуждения'));
    assert.ok(content(page).includes('новых комментариев нет.'));
    assert.ok(!content(page).includes('Жалоб нет.'));
});

test('unreported comments are shown with a count and discussion link; read history stays visible', async t => {
    fixture.feed = { comments: [comment], unread_count: 1, next_offset: null };
    const page = await mount(t);
    assert.ok(content(page).includes('новые комментарии (1)'));
    assert.ok(content(page).includes(comment.text));
    assert.equal(page.root.findByType('a').props.href, '/lesson/lesson/?discussion=task#block-task');
    fixture.feed = { ...fixture.feed, unread_count: 0, comments: [{ ...comment, is_unread: false }] };
    await act(async () => fixture.refresh());
    assert.ok(content(page).includes('новых комментариев нет.'));
    assert.ok(content(page).includes(comment.text));
});

test('older comments remain accessible through pagination', async t => {
    fixture.feed = { comments: [comment], unread_count: 51, next_offset: 50 };
    const page = await mount(t);
    fixture.feed = { comments: [{ ...comment, id: 2, text: 'Older comment' }], unread_count: 51, next_offset: null };
    const next = page.root.findAllByType('button').find(node => node.children.join('') === 'Следующие');
    await act(async () => next.props.onClick());
    assert.ok(fixture.get.mock.calls.some(call => call.arguments[1]?.params.offset === 50));
    assert.ok(content(page).includes('Older comment'));
    assert.ok(!content(page).includes(comment.text));
});
