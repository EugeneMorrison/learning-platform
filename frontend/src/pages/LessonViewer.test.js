import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React, { act, StrictMode } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

// Load the real viewer, QuizBlock and quizState with JSX support. Only network,
// browser decoration and unrelated blocks are stubbed; React hooks are real.
const fixture = globalThis.__quizLoadingTest = { setLessonBar() {} };
const server = await createServer({
    configFile: false,
    ssr: { noExternal: ['react-router-dom'] },
    server: { middlewareMode: true },
    plugins: [{
        name: 'quiz-test-boundaries',
        enforce: 'pre',
        resolveId(source) {
            if (source === '../api') return '\0quiz-api';
            if (source === 'react-router-dom') return '\0quiz-router';
            if (source === '../lib/lessonBar') return '\0quiz-bar';
            if (source === '../lib/contentImages') return '\0quiz-images';
            if ((source.startsWith('../components/') && !source.endsWith('/QuizBlock'))
                || source === './DiscussionPanel') return '\0quiz-decoration';
        },
        load(id) {
            if (id === '\0quiz-api') return `
                const api = { get: (...args) => globalThis.__quizLoadingTest.get(...args),
                    post: (...args) => globalThis.__quizLoadingTest.post(...args) };
                export default api;
                export const getLesson = id => api.get('/lessons/' + id + '/');
                export const getBlocks = id => api.get('/blocks/?lesson=' + id);
            `;
            if (id === '\0quiz-router') return `
                export const useParams = () => ({ lessonId: 'lesson' });
                export const useLocation = () => ({ hash: '', search: '' });
                export const Link = () => null;
            `;
            if (id === '\0quiz-bar') return 'export const useSetLessonBar = () => globalThis.__quizLoadingTest.setLessonBar;';
            if (id === '\0quiz-images') return `
                export const wrapImages = html => html;
                export const wrapTables = html => html;
                export const watchFigureOverflow = () => () => {};
            `;
            if (id === '\0quiz-decoration') return 'export default function Decoration() { return null; } export const DiscussionBadge = () => null;';
        },
    }],
});
const { default: LessonViewer } = await server.ssrLoadModule('/src/pages/LessonViewer.jsx');
after(() => server.close());

const content = { question: 'Question', options: ['a', 'keys', 'c', 'd'] };
const saved = {
    block: 'quiz', is_correct: true,
    answer: { selected: 1, display_order: [3, 0, 1, 2], quiz_snapshot: content },
};
const lesson = { id: 'lesson', course: 'course', title: 'Lesson', next_lesson_id: 'next' };
let progress;
let blocks;

beforeEach(t => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = { location: { pathname: '/lesson/lesson/' } };
    globalThis.document = { querySelector: () => null };
    globalThis.localStorage = { getItem: () => 'token' };
    progress = [structuredClone(saved)];
    blocks = [{ id: 'quiz', type: 'QUIZ', content, updated_at: '2026-11-01T00:00:00Z' }];
    fixture.get = async url => {
        if (url.startsWith('/lessons/')) return { data: lesson };
        if (url.startsWith('/blocks/')) return { data: blocks };
        if (url.startsWith('/courses/')) return { data: { author: 'author' } };
        if (url === '/auth/me/') return { data: null };
        if (url.startsWith('/progress/')) return { data: progress };
        throw Error(`Unexpected request: ${url}`);
    };
    fixture.post = async (_url, payload) => {
        const selected = payload.answer.selected;
        const correct = blocks[0].content.multiple_answers
            ? Array.isArray(selected) && selected.length === 2 && selected.includes(1) && selected.includes(3)
            : selected === 1;
        const record = { block: 'quiz', is_correct: correct,
            recorded: !progress.some(row => row.is_correct === true),
            answer: { ...payload.answer, ...(correct ? { quiz_snapshot: blocks[0].content } : {}) } };
        if (record.recorded) progress = [structuredClone(record)];
        return { data: record };
    };
    // React test renderer's deprecation notice and expected network errors.
    t.mock.method(console, 'error', () => {});
});

async function mount(t, strict = false) {
    let renderer;
    await act(async () => {
        const page = React.createElement(LessonViewer);
        renderer = create(strict ? React.createElement(StrictMode, null, page) : page);
    });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}

function options(renderer) {
    return renderer.root.findAll(node => node.type === 'button'
        && node.props.className?.split(' ').includes('quiz-option'));
}

function displayed(renderer) {
    return options(renderer).map(node => node.findAllByType('span').at(-1).props.dangerouslySetInnerHTML.__html);
}

async function clickAction(renderer, text) {
    const button = renderer.root.findAllByType('button').find(node => node.props.children === text);
    assert.ok(button, `Expected action: ${text}`);
    await act(async () => button.props.onClick());
}

async function choose(renderer, texts) {
    for (const text of texts) {
        await act(async () => options(renderer)[displayed(renderer).indexOf(text)].props.onClick());
    }
}

test('failed progress retrieval must not render a completed quiz with a new shuffle', async t => {
    const get = fixture.get;
    fixture.get = url => url.startsWith('/progress/')
        ? Promise.reject(Error('Temporary progress read failure')) : get(url);
    t.mock.method(Math, 'random', () => 0);
    const renderer = await mount(t);
    assert.equal(options(renderer).length, 0, 'unknown progress must not be treated as unanswered');
    assert.equal(renderer.root.findAllByProps({ role: 'alert' }).length, 1);
    fixture.get = get;
    const retried = await mount(t);
    assert.deepEqual(displayed(retried), ['d', 'a', 'keys', 'c']);
    assert.equal(options(retried)[2].props['aria-pressed'], true);
});

test('Strict Mode must not expose quizzes while the active progress read is pending', async t => {
    const get = fixture.get;
    const requests = [];
    fixture.get = url => url.startsWith('/progress/')
        ? new Promise(resolve => requests.push(resolve)) : get(url);
    const renderer = await mount(t, true);
    assert.equal(options(renderer).length, 0);
    // On the old loader both effect runs fetch progress; finishing the stale
    // request incorrectly releases the current page's loading gate.
    if (requests.length > 1) {
        await act(async () => requests[0]({ data: [] }));
        assert.equal(options(renderer).length, 0, 'canceled load must not mount a randomized quiz');
    }
    await act(async () => requests.at(-1)({ data: progress }));
    assert.deepEqual(displayed(renderer), ['d', 'a', 'keys', 'c']);
    assert.equal(options(renderer)[2].props['aria-pressed'], true);
});

for (const multiple of [false, true]) {
    test(`${multiple ? 'multiple' : 'single'} answers: first success preserves order and highlights across refreshes`, async t => {
        blocks = [{ ...blocks[0], content: { ...content, multiple_answers: multiple } }];
        progress = [];
        t.mock.method(Math, 'random', () => 0);
        const first = await mount(t);
        const order = displayed(first);
        for (const text of multiple ? ['keys', 'd'] : ['keys']) {
            await act(async () => options(first)[order.indexOf(text)].props.onClick());
        }
        await act(async () => first.root.findAllByType('button').find(node => node.props.onClick
            && node.props.children === 'Проверить ответ').props.onClick());
        assert.deepEqual(progress[0].answer.display_order.map(index => content.options[index]), order);
        const selectedPositions = options(first).map(node => node.props['aria-pressed']);
        for (const random of [0.99, 0.4, 0]) {
            Math.random = () => random;
            const refreshed = await mount(t);
            assert.deepEqual(displayed(refreshed), order);
            assert.deepEqual(options(refreshed).map(node => node.props['aria-pressed']), selectedPositions);
            assert.equal(options(refreshed).filter(node => node.props.className.includes('--correct')).length, multiple ? 2 : 1);
        }
    });
}

test('saved historical snapshot restores before randomization even after author edits', async t => {
    blocks = [{ ...blocks[0], content: { question: 'Edited', options: ['replacement'] } }];
    t.mock.method(Math, 'random', () => { throw Error('completed quiz must not randomize'); });
    const renderer = await mount(t);
    assert.deepEqual(displayed(renderer), ['d', 'a', 'keys', 'c']);
    assert.equal(options(renderer)[2].props['aria-pressed'], true);
});

test('legacy completed answers without order metadata retain a stable compatible fallback', async t => {
    progress = [{ block: 'quiz', is_correct: true, answer: { selected: 1 } }];
    t.mock.method(Math, 'random', () => { throw Error('legacy completion must not randomize'); });
    for (let refresh = 0; refresh < 3; refresh++) {
        const renderer = await mount(t);
        assert.deepEqual(displayed(renderer), content.options);
        assert.equal(options(renderer)[1].props['aria-pressed'], true);
    }
});

for (const multiple of [false, true]) {
    const mode = multiple ? 'multiple' : 'single';
    for (const precedingCorrect of [false, true]) {
        test(`${mode}: rendered options use the new retry permutation after ${precedingCorrect ? 'success' : 'failure'}`, async t => {
            progress = [];
            blocks = [{ ...blocks[0], content: {
                ...content, multiple_answers: multiple, shuffle_options: true,
            } }];
            let draw = 0.99;
            t.mock.method(Math, 'random', () => draw);
            const renderer = await mount(t);
            // Fisher-Yates with .99 leaves the author order unchanged.
            assert.deepEqual(displayed(renderer), ['a', 'keys', 'c', 'd']);
            await choose(renderer, precedingCorrect ? (multiple ? ['keys', 'd'] : ['keys']) : ['a']);
            await clickAction(renderer, 'Проверить ответ');
            const stored = structuredClone(progress);

            // Draws of zero produce original indices [1, 2, 3, 0]. Assert
            // rendered button text order, not just the random call count.
            draw = 0;
            await clickAction(renderer, precedingCorrect ? 'Решить снова' : 'Попробовать снова');
            assert.deepEqual(displayed(renderer), ['keys', 'c', 'd', 'a']);
            assert.ok(options(renderer).every(node => !node.props['aria-pressed'] && !node.props.disabled));
            assert.deepEqual(progress, stored);
            // Allow parent progress updates and effects to settle; neither
            // may put the previous permutation back into the rendered quiz.
            await act(async () => {});
            assert.deepEqual(displayed(renderer), ['keys', 'c', 'd', 'a']);

            await choose(renderer, ['a']);
            await clickAction(renderer, 'Проверить ответ');
            draw = 0.99;
            await clickAction(renderer, 'Попробовать снова');
            assert.deepEqual(displayed(renderer), ['a', 'keys', 'c', 'd']);
            if (precedingCorrect) {
                assert.deepEqual(progress, stored);
                const reopened = await mount(t);
                assert.deepEqual(displayed(reopened), ['a', 'keys', 'c', 'd']);
                assert.ok(options(reopened).filter(node => node.props['aria-pressed'])
                    .every(node => node.props.className.includes('--correct')));
                assert.equal(options(reopened).filter(node => node.props['aria-pressed']).length, multiple ? 2 : 1);
            }
        });
    }

    test(`${mode}: incorrect retry renders a different order even when the random draw repeats`, async t => {
        progress = [];
        blocks = [{ ...blocks[0], content: { ...content, multiple_answers: multiple } }];
        // Force the random draw to repeat the immediately preceding order.
        const random = t.mock.method(Math, 'random', () => 0);
        const renderer = await mount(t);
        const order = displayed(renderer);
        await choose(renderer, ['a']);
        await clickAction(renderer, 'Проверить ответ');
        assert.equal(options(renderer).filter(node => node.props.className.includes('--wrong')).length, 1);
        assert.ok(options(renderer).every(node => node.props.disabled), 'retry must explicitly start a new attempt');
        const calls = random.mock.callCount();
        await clickAction(renderer, 'Попробовать снова');
        assert.equal(random.mock.callCount() - calls, content.options.length - 1);
        assert.notDeepEqual(displayed(renderer), order);
        assert.ok(options(renderer).every(node => node.props['aria-pressed'] === false));
        assert.equal(renderer.root.findAllByProps({ role: 'status' }).length, 0);
        await choose(renderer, multiple ? ['keys', 'd'] : ['keys']);
        const retryOrder = displayed(renderer);
        await clickAction(renderer, 'Проверить ответ');
        assert.deepEqual(progress[0].answer.display_order.map(index => content.options[index]), retryOrder);
        const reopened = await mount(t);
        assert.deepEqual(displayed(reopened), retryOrder);
    });

    test(`${mode}: correct retry draws a fresh shuffle without changing saved completion`, async t => {
        progress = [];
        blocks = [{ ...blocks[0], content: { ...content, multiple_answers: multiple } }];
        const random = t.mock.method(Math, 'random', () => 0);
        const renderer = await mount(t);
        await choose(renderer, multiple ? ['keys', 'd'] : ['keys']);
        await clickAction(renderer, 'Проверить ответ');
        const stored = structuredClone(progress);
        const completedOrder = displayed(renderer);
        const calls = random.mock.callCount();
        await clickAction(renderer, 'Решить снова');
        assert.equal(random.mock.callCount() - calls, content.options.length - 1);
        assert.notDeepEqual(displayed(renderer), completedOrder);
        assert.ok(options(renderer).every(node => !node.props['aria-pressed'] && !node.props.disabled));
        assert.deepEqual(progress, stored);
        await choose(renderer, multiple ? ['keys', 'd'] : ['keys']);
        await clickAction(renderer, 'Проверить ответ');
        const practiceOrder = displayed(renderer);
        const nextCalls = random.mock.callCount();
        await clickAction(renderer, 'Решить снова');
        assert.equal(random.mock.callCount() - nextCalls, content.options.length - 1);
        assert.notDeepEqual(displayed(renderer), practiceOrder);
        assert.deepEqual(progress, stored);
    });

    test(`${mode}: practice displays its own success while refresh restores the first saved solution`, async t => {
        blocks = [{ ...blocks[0], content: { ...content, multiple_answers: multiple } }];
        progress = [{ ...structuredClone(saved), answer: { ...structuredClone(saved.answer),
            selected: multiple ? [1, 3] : 1, quiz_snapshot: blocks[0].content } }];
        const stored = structuredClone(progress);
        t.mock.method(Math, 'random', () => 0);
        const renderer = await mount(t);
        const completedOrder = displayed(renderer);
        const highlights = options(renderer).map(node => node.props['aria-pressed']);
        await clickAction(renderer, 'Решить снова');
        await choose(renderer, ['a']);
        await clickAction(renderer, 'Проверить ответ');
        Math.random = () => 0.99;
        await clickAction(renderer, 'Попробовать снова');
        await choose(renderer, multiple ? ['keys', 'd'] : ['keys']);
        const practiceOrder = displayed(renderer);
        const practiceHighlights = options(renderer).map(node => node.props['aria-pressed']);
        await clickAction(renderer, 'Проверить ответ');
        assert.deepEqual(displayed(renderer), practiceOrder);
        assert.deepEqual(options(renderer).map(node => node.props['aria-pressed']), practiceHighlights);
        assert.deepEqual(progress, stored);
        for (let refresh = 0; refresh < 3; refresh++) {
            const reopened = await mount(t);
            assert.deepEqual(displayed(reopened), completedOrder);
            assert.deepEqual(options(reopened).map(node => node.props['aria-pressed']), highlights);
        }
    });
}

test('incorrect retry respects the author setting to disable shuffling', async t => {
    progress = [];
    blocks = [{ ...blocks[0], content: { ...content, shuffle_options: false } }];
    t.mock.method(Math, 'random', () => { throw Error('shuffle disabled'); });
    const renderer = await mount(t);
    await choose(renderer, ['a']);
    await clickAction(renderer, 'Проверить ответ');
    await clickAction(renderer, 'Попробовать снова');
    assert.deepEqual(displayed(renderer), content.options);
    assert.ok(options(renderer).every(node => !node.props['aria-pressed']));
});

test('practice on an edited quiz uses current options without replacing the historical completion', async t => {
    blocks = [{ ...blocks[0], content: { question: 'Edited question', options: ['new wrong', 'new correct'] } }];
    const stored = structuredClone(progress);
    t.mock.method(Math, 'random', () => 0);
    const renderer = await mount(t);
    const historicalOrder = displayed(renderer);
    await clickAction(renderer, 'Решить снова');
    assert.deepEqual(displayed(renderer), ['new correct', 'new wrong']);
    await choose(renderer, ['new correct']);
    await clickAction(renderer, 'Проверить ответ');
    assert.deepEqual(displayed(renderer), ['new correct', 'new wrong']);
    assert.equal(options(renderer)[0].props['aria-pressed'], true);
    assert.deepEqual(progress, stored);
    const reopened = await mount(t);
    assert.deepEqual(displayed(reopened), historicalOrder);
    assert.equal(options(reopened)[2].props['aria-pressed'], true);
});

test('practice can be canceled back to legacy saved work without changing progress', async t => {
    progress = [{ block: 'quiz', is_correct: true, answer: { selected: 1 } }];
    const stored = structuredClone(progress);
    const renderer = await mount(t);
    await clickAction(renderer, 'Решить снова');
    await choose(renderer, ['a']);
    await clickAction(renderer, 'Вернуться к сохранённому решению');
    assert.deepEqual(displayed(renderer), content.options);
    assert.equal(options(renderer)[1].props['aria-pressed'], true);
    assert.ok(options(renderer).every(node => node.props.disabled));
    assert.deepEqual(progress, stored);
});

test('retry changes rendered text even when a shuffle only exchanges identical options', async t => {
    progress = [];
    blocks = [{ ...blocks[0], content: { ...content, options: ['same', 'same', 'different'], shuffle_options: true } }];
    let draws = [0.99, 0.99];
    t.mock.method(Math, 'random', () => {
        assert.ok(draws.length, 'retry must not loop or request extra random draws');
        return draws.shift();
    });
    const renderer = await mount(t);
    assert.deepEqual(displayed(renderer), ['same', 'same', 'different']);
    await choose(renderer, ['same']);
    await clickAction(renderer, 'Проверить ответ');
    // Only exchanges the two identical strings: indices [1, 0, 2].
    draws = [0.99, 0];
    await clickAction(renderer, 'Попробовать снова');
    assert.deepEqual(displayed(renderer), ['different', 'same', 'same']);
    assert.equal(draws.length, 0);
});

test('retry terminates normally when all option text is identical', async t => {
    progress = [];
    blocks = [{ ...blocks[0], content: { ...content, options: ['same', 'same'], shuffle_options: true } }];
    const random = t.mock.method(Math, 'random', () => 0);
    const renderer = await mount(t);
    // With this draw original index 0 (the wrong answer) is displayed last.
    await act(async () => options(renderer)[1].props.onClick());
    await clickAction(renderer, 'Проверить ответ');
    const calls = random.mock.callCount();
    await clickAction(renderer, 'Попробовать снова');
    assert.deepEqual(displayed(renderer), ['same', 'same']);
    assert.equal(random.mock.callCount() - calls, 1);
    assert.ok(options(renderer).every(node => !node.props.disabled));
});
