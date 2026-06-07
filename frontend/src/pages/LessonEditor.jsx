import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { pycharmDarcula } from '../components/pycharmDarcula';
import RichTextEditor from '../components/RichTextEditor';
import UserBadge from '../components/UserBadge';
import { parseTemplate } from '../lib/fillTemplate';
import api from '../api';

const TYPE_LABELS = {
    TEXT: '📝 Теория',
    QUIZ: '❓ Тест',
    CODE: '💻 Задача с кодом',
    FILL: '✍️ Заполнить пропуски',
};

function defaultContent(type) {
    switch (type) {
        case 'TEXT':
            return { html: '' };
        case 'QUIZ':
            return { question: '', options: ['', ''], correct_answer: 0, explanation: '' };
        case 'CODE':
            return { prompt: '', starter_code: '# Ваш код здесь\n', solution: '', tests: [{ input: '', expected: '' }] };
        case 'FILL':
            return { prompt: '', template: '', case_sensitive: false, explanation: '' };
        default:
            return {};
    }
}

function stripHtml(html) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html || '';
    return (tmp.textContent || tmp.innerText || '').trim();
}

function LessonEditor() {
    const { lessonId } = useParams();
    const navigate = useNavigate();

    const [lesson, setLesson] = useState(null);
    const [blocks, setBlocks] = useState([]);
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // The block currently open in the form: { id: string|null, type, content }.
    // id === null means we're creating a new block.
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState('');
    const [busy, setBusy] = useState(false); // reorder/delete in flight

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [lessonId]);

    async function load() {
        try {
            const [meRes, lessonRes, blocksRes] = await Promise.all([
                api.get('/auth/me/'),
                api.get(`/lessons/${lessonId}/`),
                api.get(`/blocks/?lesson=${lessonId}`),
            ]);
            setUser(meRes.data);
            setLesson(lessonRes.data);
            setBlocks(blocksRes.data);
        } catch (err) {
            console.error('Failed to load lesson editor:', err);
            setError('Не удалось загрузить урок.');
        } finally {
            setLoading(false);
        }
    }

    async function reloadBlocks() {
        const res = await api.get(`/blocks/?lesson=${lessonId}`);
        setBlocks(res.data);
    }

    function nextOrderIndex() {
        if (blocks.length === 0) return 1;
        return Math.max(...blocks.map(b => b.order_index)) + 1;
    }

    function startAdd(type) {
        setFormError('');
        setDraft({ id: null, type, content: defaultContent(type) });
    }

    function startEdit(block) {
        setFormError('');
        // Deep-ish clone so editing doesn't mutate state until save.
        setDraft({ id: block.id, type: block.type, content: JSON.parse(JSON.stringify(block.content)) });
    }

    function cancelDraft() {
        setDraft(null);
        setFormError('');
    }

    function setContent(updater) {
        setDraft(d => ({ ...d, content: updater(d.content) }));
    }

    function validate(type, content) {
        if (type === 'TEXT') {
            if (!stripHtml(content.html)) return 'Добавьте текст теории.';
        } else if (type === 'QUIZ') {
            if (!stripHtml(content.question)) return 'Введите вопрос.';
            const filled = content.options.filter(o => o.trim());
            if (filled.length < 2) return 'Нужно минимум два варианта ответа.';
            if (content.correct_answer == null || !content.options[content.correct_answer]?.trim())
                return 'Отметьте правильный вариант ответа.';
        } else if (type === 'CODE') {
            if (!stripHtml(content.prompt)) return 'Опишите условие задачи.';
            if (!content.starter_code.trim()) return 'Добавьте стартовый код.';
        } else if (type === 'FILL') {
            const blanks = (content.template || '').match(/\{\{(.*?)\}\}/g) || [];
            const hasAnswer = blanks.some(b => b.replace(/\{\{|\}\}/g, '').trim());
            if (!hasAnswer) return 'Добавьте шаблон хотя бы с одним пропуском, например: print({{8}})';
        }
        return '';
    }

    async function handleSave() {
        const { id, type } = draft;
        let content = draft.content;

        // Clean up before saving.
        if (type === 'QUIZ') {
            const options = content.options.map(o => o.trim()).filter(Boolean);
            // Keep correct_answer pointing at the same option after trimming/removal.
            const correctText = content.options[content.correct_answer];
            const correct_answer = Math.max(0, options.indexOf((correctText || '').trim()));
            content = { ...content, options, correct_answer };
        } else if (type === 'CODE') {
            const tests = (content.tests || [])
                .filter(t => t.input.trim() !== '' || t.expected.trim() !== '');
            content = { ...content, tests };
        }

        const err = validate(type, content);
        if (err) { setFormError(err); return; }

        setSaving(true);
        setFormError('');
        try {
            if (id === null) {
                await api.post('/blocks/', {
                    lesson: lessonId,
                    type,
                    order_index: nextOrderIndex(),
                    content,
                });
            } else {
                const existing = blocks.find(b => b.id === id);
                await api.put(`/blocks/${id}/`, {
                    lesson: lessonId,
                    type,
                    order_index: existing.order_index,
                    content,
                });
            }
            await reloadBlocks();
            setDraft(null);
        } catch (e) {
            console.error('Failed to save block:', e);
            setFormError('Не удалось сохранить блок. Проверьте поля.');
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete(block) {
        if (!window.confirm('Удалить этот блок?')) return;
        setBusy(true);
        try {
            await api.delete(`/blocks/${block.id}/`);
            if (draft?.id === block.id) setDraft(null);
            await reloadBlocks();
        } catch (e) {
            console.error('Failed to delete block:', e);
            alert('Не удалось удалить блок.');
        } finally {
            setBusy(false);
        }
    }

    // Swap order_index with the neighbour. Uses a temporary free index to dodge
    // the (lesson, order_index) unique constraint during the swap.
    async function moveBlock(index, dir) {
        const target = index + dir;
        if (target < 0 || target >= blocks.length) return;
        setBusy(true);
        try {
            const a = blocks[index];
            const b = blocks[target];
            const temp = Math.max(...blocks.map(x => x.order_index)) + 1;
            await api.patch(`/blocks/${a.id}/`, { order_index: temp });
            await api.patch(`/blocks/${b.id}/`, { order_index: a.order_index });
            await api.patch(`/blocks/${a.id}/`, { order_index: b.order_index });
            await reloadBlocks();
        } catch (e) {
            console.error('Failed to reorder blocks:', e);
            alert('Не удалось изменить порядок.');
            await reloadBlocks();
        } finally {
            setBusy(false);
        }
    }

    if (loading) return <p style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>Загрузка...</p>;
    if (error) return <p style={{ padding: 40, textAlign: 'center', color: '#dc2626' }}>{error}</p>;
    if (user?.role !== 'AUTHOR') {
        return <p style={{ padding: 40, textAlign: 'center', color: '#dc2626' }}>Только автор курса может редактировать урок.</p>;
    }

    return (
        <div style={{ maxWidth: 800, margin: '40px auto', padding: 20 }}>
            <UserBadge user={user} />
            <button onClick={() => navigate(`/courses/${lesson.course}/`)} style={{ marginBottom: 20 }}>
                ← Назад к курсу
            </button>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div>
                    <div style={{ fontSize: 13, color: '#64748b' }}>Редактор урока {lesson.order_index}</div>
                    <h2 style={{ margin: '4px 0 0' }}>{lesson.title}</h2>
                </div>
                <button onClick={() => navigate(`/lesson/${lessonId}/`)} style={ghostBtn}>
                    👁 Предпросмотр
                </button>
            </div>
            <hr style={{ margin: '20px 0' }} />

            {/* Existing blocks */}
            {blocks.length === 0 && !draft && (
                <p style={{ color: '#64748b' }}>В этом уроке пока нет блоков. Добавьте первый блок ниже.</p>
            )}

            {blocks.map((block, index) => (
                <div key={block.id}>
                    {draft?.id === block.id ? (
                        <BlockForm
                            draft={draft}
                            setContent={setContent}
                            onSave={handleSave}
                            onCancel={cancelDraft}
                            saving={saving}
                            formError={formError}
                        />
                    ) : (
                        <div style={blockCard}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                                <div style={{ minWidth: 0 }}>
                                    <span style={badge}>{TYPE_LABELS[block.type]}</span>
                                    <div style={{ marginTop: 8, color: '#475569', fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 520 }}>
                                        {blockPreview(block)}
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                                    <button title="Вверх" disabled={busy || index === 0} onClick={() => moveBlock(index, -1)} style={iconBtn}>↑</button>
                                    <button title="Вниз" disabled={busy || index === blocks.length - 1} onClick={() => moveBlock(index, 1)} style={iconBtn}>↓</button>
                                    <button disabled={busy} onClick={() => startEdit(block)} style={iconBtn}>✎ Изменить</button>
                                    <button disabled={busy} onClick={() => handleDelete(block)} style={deleteBtn}>Удалить</button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            ))}

            {/* New block form */}
            {draft?.id === null && (
                <BlockForm
                    draft={draft}
                    setContent={setContent}
                    onSave={handleSave}
                    onCancel={cancelDraft}
                    saving={saving}
                    formError={formError}
                />
            )}

            {/* Add block buttons */}
            {!draft && (
                <div style={{ marginTop: 24, padding: 16, border: '1px dashed #cbd5e1', borderRadius: 8, background: '#f8fafc' }}>
                    <div style={{ fontWeight: 600, marginBottom: 10, color: '#334155' }}>Добавить блок:</div>
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        {['TEXT', 'QUIZ', 'CODE'].map(type => (
                            <button key={type} onClick={() => startAdd(type)} style={addBtn}>
                                {TYPE_LABELS[type]}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

function blockPreview(block) {
    if (block.type === 'TEXT') return stripHtml(block.content.html) || '(пусто)';
    if (block.type === 'QUIZ') return stripHtml(block.content.question) || '(без вопроса)';
    if (block.type === 'CODE') return stripHtml(block.content.prompt) || '(без условия)';
    if (block.type === 'FILL') return block.content.template || stripHtml(block.content.prompt) || '(пустой шаблон)';
    return '';
}

// =============================================================================
// BLOCK FORM (per-type fields)
// =============================================================================

function BlockForm({ draft, setContent, onSave, onCancel, saving, formError }) {
    const { type, content } = draft;

    return (
        <div style={{ ...blockCard, borderLeft: '4px solid #0C4B33', background: '#fbfdfc' }}>
            <div style={{ fontWeight: 700, marginBottom: 14 }}>
                {draft.id === null ? 'Новый блок' : 'Редактирование'}: {TYPE_LABELS[type]}
            </div>

            {type === 'TEXT' && (
                <Field label="Текст теории">
                    <RichTextEditor
                        value={content.html}
                        onChange={(html) => setContent(c => ({ ...c, html }))}
                        placeholder="Напишите теорию урока..."
                    />
                </Field>
            )}

            {type === 'QUIZ' && <QuizFields content={content} setContent={setContent} />}

            {type === 'CODE' && <CodeFields content={content} setContent={setContent} />}

            {type === 'FILL' && <FillFields content={content} setContent={setContent} />}

            {formError && <p style={{ color: '#dc2626', marginTop: 8 }}>{formError}</p>}

            <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
                <button onClick={onSave} disabled={saving} style={saveBtn}>
                    {saving ? 'Сохранение...' : 'Сохранить'}
                </button>
                <button onClick={onCancel} disabled={saving} style={ghostBtn}>Отмена</button>
            </div>
        </div>
    );
}

function QuizFields({ content, setContent }) {
    return (
        <>
            <Field label="Вопрос" hint="Используйте «Код-блок» для кода и кнопку «Картинка» для изображений и формул.">
                <RichTextEditor
                    value={content.question}
                    onChange={(html) => setContent(c => ({ ...c, question: html }))}
                    placeholder="Что выведет этот код?"
                />
            </Field>

            <Field label="Варианты ответа" hint="Отметьте кружком правильный вариант.">
                {content.options.map((opt, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <input
                            type="radio"
                            name="correct"
                            checked={content.correct_answer === i}
                            onChange={() => setContent(c => ({ ...c, correct_answer: i }))}
                            title="Правильный ответ"
                        />
                        <input
                            type="text"
                            value={opt}
                            onChange={e => setContent(c => {
                                const options = [...c.options];
                                options[i] = e.target.value;
                                return { ...c, options };
                            })}
                            style={{ ...input, flex: 1, fontFamily: "'JetBrains Mono', Consolas, monospace" }}
                            placeholder={`Вариант ${i + 1}`}
                        />
                        <button
                            type="button"
                            onClick={() => setContent(c => {
                                if (c.options.length <= 2) return c;
                                const options = c.options.filter((_, idx) => idx !== i);
                                let correct_answer = c.correct_answer;
                                if (correct_answer === i) correct_answer = 0;
                                else if (correct_answer > i) correct_answer -= 1;
                                return { ...c, options, correct_answer };
                            })}
                            disabled={content.options.length <= 2}
                            style={iconBtn}
                            title="Удалить вариант"
                        >✕</button>
                    </div>
                ))}
                <button
                    type="button"
                    onClick={() => setContent(c => ({ ...c, options: [...c.options, ''] }))}
                    style={{ ...ghostBtn, padding: '6px 12px' }}
                >+ Вариант</button>
            </Field>

            <Field label="Пояснение (показывается при верном ответе)">
                <input
                    type="text"
                    value={content.explanation}
                    onChange={e => setContent(c => ({ ...c, explanation: e.target.value }))}
                    style={input}
                    placeholder="Почему этот ответ правильный"
                />
            </Field>
        </>
    );
}

function CodeFields({ content, setContent }) {
    return (
        <>
            <Field label="Условие задачи">
                <RichTextEditor
                    value={content.prompt}
                    onChange={(html) => setContent(c => ({ ...c, prompt: html }))}
                    placeholder="Опишите, что нужно сделать..."
                />
            </Field>

            <Field label="Стартовый код">
                <div style={cmWrap}>
                    <CodeMirror
                        value={content.starter_code}
                        height="120px"
                        theme="none"
                        extensions={[python(), pycharmDarcula]}
                        onChange={(val) => setContent(c => ({ ...c, starter_code: val }))}
                    />
                </div>
            </Field>

            <Field label="Решение (необязательно, студентам не показывается)">
                <div style={cmWrap}>
                    <CodeMirror
                        value={content.solution || ''}
                        height="120px"
                        theme="none"
                        extensions={[python(), pycharmDarcula]}
                        onChange={(val) => setContent(c => ({ ...c, solution: val }))}
                    />
                </div>
            </Field>

            <Field label="Тесты" hint="Ввод подаётся в stdin, ожидаемый вывод сравнивается со stdout. Пустые тесты игнорируются.">
                {(content.tests || []).map((test, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'flex-start' }}>
                        <textarea
                            value={test.input}
                            onChange={e => setContent(c => {
                                const tests = [...c.tests];
                                tests[i] = { ...tests[i], input: e.target.value };
                                return { ...c, tests };
                            })}
                            style={{ ...input, flex: 1, minHeight: 48, fontFamily: "'JetBrains Mono', Consolas, monospace" }}
                            placeholder="Ввод (stdin)"
                        />
                        <textarea
                            value={test.expected}
                            onChange={e => setContent(c => {
                                const tests = [...c.tests];
                                tests[i] = { ...tests[i], expected: e.target.value };
                                return { ...c, tests };
                            })}
                            style={{ ...input, flex: 1, minHeight: 48, fontFamily: "'JetBrains Mono', Consolas, monospace" }}
                            placeholder="Ожидаемый вывод (stdout)"
                        />
                        <button
                            type="button"
                            onClick={() => setContent(c => ({ ...c, tests: c.tests.filter((_, idx) => idx !== i) }))}
                            style={iconBtn}
                            title="Удалить тест"
                        >✕</button>
                    </div>
                ))}
                <button
                    type="button"
                    onClick={() => setContent(c => ({ ...c, tests: [...(c.tests || []), { input: '', expected: '' }] }))}
                    style={{ ...ghostBtn, padding: '6px 12px' }}
                >+ Тест</button>
            </Field>
        </>
    );
}

function FillFields({ content, setContent }) {
    const segments = parseTemplate(content.template || '');
    const hasBlanks = segments.some(s => s.type === 'blank');

    return (
        <>
            <Field label="Описание (условие)" hint="Текст и код над пропусками. Можно оставить пустым.">
                <RichTextEditor
                    value={content.prompt}
                    onChange={(html) => setContent(c => ({ ...c, prompt: html }))}
                    placeholder="Например: Модуль подключили так… Напишите строку, которая выведет факториал числа 8."
                />
            </Field>

            <Field
                label="Шаблон с пропусками"
                hint="Отметьте пропуски как {{ответ}}. Несколько верных ответов — через | , например: print({{math.factorial(8)|factorial(8)}})"
            >
                <textarea
                    value={content.template}
                    onChange={e => setContent(c => ({ ...c, template: e.target.value }))}
                    style={{ ...input, minHeight: 70, fontFamily: "'JetBrains Mono', Consolas, monospace" }}
                    placeholder="print({{8}})"
                />
            </Field>

            {/* Live preview of how the blanks will look + which answers are accepted */}
            {hasBlanks && (
                <Field label="Предпросмотр">
                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, rowGap: 10 }}>
                        {segments.map((seg, idx) => {
                            if (seg.type === 'text') {
                                return seg.value.trim() === ''
                                    ? <span key={idx}>{seg.value}</span>
                                    : <span key={idx} style={previewChip}>{seg.value}</span>;
                            }
                            return (
                                <span key={idx} style={previewBlank} title="Принимаемые ответы">
                                    {seg.answers.join(' / ') || '⌀'}
                                </span>
                            );
                        })}
                    </div>
                    <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>
                        В пропусках показаны принимаемые ответы — студент увидит пустые поля.
                    </div>
                </Field>
            )}

            <Field label="">
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, color: '#334155' }}>
                    <input
                        type="checkbox"
                        checked={!!content.case_sensitive}
                        onChange={e => setContent(c => ({ ...c, case_sensitive: e.target.checked }))}
                    />
                    Учитывать регистр букв
                </label>
            </Field>

            <Field label="Пояснение (показывается при верном ответе)">
                <input
                    type="text"
                    value={content.explanation || ''}
                    onChange={e => setContent(c => ({ ...c, explanation: e.target.value }))}
                    style={input}
                    placeholder="Необязательно"
                />
            </Field>
        </>
    );
}

function Field({ label, hint, children }) {
    return (
        <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontWeight: 600, marginBottom: 6, color: '#334155', fontSize: 14 }}>{label}</label>
            {hint && <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 8 }}>{hint}</div>}
            {children}
        </div>
    );
}

// =============================================================================
// Inline styles
// =============================================================================

const blockCard = {
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    padding: 16,
    marginTop: 12,
    background: 'white',
};

const badge = {
    display: 'inline-block',
    padding: '3px 10px',
    background: '#ecfdf5',
    color: '#0C4B33',
    borderRadius: 999,
    fontWeight: 600,
    fontSize: 13,
};

const input = {
    width: '100%',
    padding: '8px 10px',
    border: '1px solid #cbd5e1',
    borderRadius: 6,
    fontSize: 14,
    boxSizing: 'border-box',
};

const cmWrap = {
    border: '1px solid #cbd5e1',
    borderRadius: 6,
    overflow: 'hidden',
};

const saveBtn = {
    padding: '9px 22px', background: '#0C4B33', color: 'white',
    border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
};

const ghostBtn = {
    padding: '9px 18px', background: 'white', color: '#334155',
    border: '1px solid #cbd5e1', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
};

const addBtn = {
    padding: '10px 18px', background: 'white', color: '#0C4B33',
    border: '1px solid #0C4B33', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
};

const iconBtn = {
    padding: '6px 10px', background: 'white', color: '#475569',
    border: '1px solid #cbd5e1', borderRadius: 6, cursor: 'pointer', fontSize: 13,
};

const deleteBtn = {
    padding: '6px 12px', background: 'white', color: '#dc2626',
    border: '1px solid #fecaca', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 500,
};

const previewChip = {
    fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 14,
    background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 6,
    padding: '6px 8px', whiteSpace: 'pre', color: '#334155',
};

const previewBlank = {
    fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 14,
    background: '#dcfce7', border: '2px solid #16a34a', borderRadius: 999,
    padding: '4px 12px', color: '#15803d', fontWeight: 600,
};

export default LessonEditor;
