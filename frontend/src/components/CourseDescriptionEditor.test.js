import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import React, { act } from 'react';
import { create } from 'react-test-renderer';
import { createServer } from 'vite';

const server = await createServer({ configFile: false, server: { middlewareMode: true, hmr: false } });
const { default: Editor } = await server.ssrLoadModule('/src/components/CourseDescriptionEditor.jsx');
after(() => server.close());

async function mount(t, props) {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    t.mock.method(console, 'error', () => {});
    let renderer;
    await act(async () => { renderer = create(React.createElement(Editor, props)); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    return renderer;
}
const button = (renderer, label) => renderer.root.findAllByType('button').find(node => node.children.join('') === label);
const change = (renderer, value) => act(async () => renderer.root.findByType('textarea').props.onChange({ target: { value } }));
const submit = renderer => act(async () => renderer.root.findByType('form').props.onSubmit({ preventDefault() {} }));

test('owner can add a description omitted at creation and see the saved text', async t => {
    let saved;
    const onSave = async value => { saved = value; };
    const renderer = await mount(t, { value: '', canEdit: true, onSave });
    await act(async () => button(renderer, '+ Добавить описание').props.onClick());
    assert.equal(renderer.root.findByType('textarea').props.value, '');
    await change(renderer, '  Learn Python\nWith examples  ');
    await submit(renderer);
    assert.equal(saved, 'Learn Python\nWith examples');
    await act(async () => renderer.update(React.createElement(Editor, { value: saved, canEdit: true, onSave })));
    assert.equal(renderer.root.findAllByType('textarea').length, 0);
    assert.ok(JSON.stringify(renderer.toJSON()).includes('Learn Python'));
    await act(async () => button(renderer, 'Редактировать описание').props.onClick());
    assert.equal(renderer.root.findByType('textarea').props.value, saved);
});

test('cancel discards edits without saving; owner can clear an existing description', async t => {
    const onSave = t.mock.fn(async () => {});
    const renderer = await mount(t, { value: 'Original', canEdit: true, onSave });
    await act(async () => button(renderer, 'Редактировать описание').props.onClick());
    await change(renderer, 'Changed');
    await act(async () => button(renderer, 'Отмена').props.onClick());
    assert.equal(onSave.mock.calls.length, 0);
    await act(async () => button(renderer, 'Редактировать описание').props.onClick());
    assert.equal(renderer.root.findByType('textarea').props.value, 'Original');
    await change(renderer, '');
    await submit(renderer);
    assert.equal(onSave.mock.calls[0].arguments[0], '');
});

test('failed save preserves the draft and allows retry', async t => {
    let fail = true;
    const renderer = await mount(t, { value: '', canEdit: true, onSave: async () => {
        if (fail) throw { response: { data: { description: ['Please try again'] } } };
    } });
    await act(async () => button(renderer, '+ Добавить описание').props.onClick());
    await change(renderer, 'Keep this draft');
    await submit(renderer);
    assert.equal(renderer.root.findByProps({ role: 'alert' }).children.join(''), 'Please try again');
    assert.equal(renderer.root.findByType('textarea').props.value, 'Keep this draft');
    fail = false;
    await submit(renderer);
    assert.equal(renderer.root.findAllByType('textarea').length, 0);
});

test('students and other readers only see saved description text', async t => {
    const renderer = await mount(t, { value: '<b>Plain text</b>\nSecond line', canEdit: false });
    assert.equal(renderer.root.findAllByType('button').length, 0);
    assert.equal(renderer.root.findAllByType('textarea').length, 0);
    assert.equal(renderer.root.findByType('p').children.join(''), '<b>Plain text</b>\nSecond line');
    await act(async () => renderer.update(React.createElement(Editor, { value: '', canEdit: false })));
    assert.equal(renderer.toJSON(), null);
});
