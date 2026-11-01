import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useNavigate, useSearchParams, useBlocker } from 'react-router-dom';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { pycharmDarcula } from '../components/pycharmDarcula';
import RichTextEditor from '../components/RichTextEditor';
import EditableTitle from '../components/EditableTitle';
import UnsavedBlockMarkers from '../components/UnsavedBlockMarkers';
import DragHandle from '../components/DragHandle';
import { useDragReorder } from '../lib/useDragReorder';
import { parseTemplate } from '../lib/fillTemplate';
import { OUTPUT_COMPARISONS } from '../lib/outputComparison';
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
            return { prompt: '', header: '', starter_code: '# Ваш код здесь\n', footer: '', solution: '', output_comparison: 'exact', tests: [{ input: '', expected: '', visible: true }] };
        case 'FILL':
            return { prompt: '', template: '', case_sensitive: false, explanation: '' };
        default:
            return {};
    }
}

// Same default as the server (api/block_content.py): when no test has a
// `visible` flag, the first DEFAULT_VISIBLE_TESTS are shown to students.
const DEFAULT_VISIBLE_TESTS = 2;

// Tests as the form edits them: each {input, expected, visible}.
// - A legacy string test means "expected output, empty stdin"
//   (block_content.normalize_test): it becomes {input: '', expected: <string>},
//   so saving keeps how it's graded (before, such blocks couldn't be saved).
// - `visible` is what students see now (block_content.test_visibility): with
//   any explicit flag, only dict tests flagged true; otherwise the first
//   DEFAULT_VISIBLE_TESTS. The "Показывать ученику" checkboxes show it, and
//   saving stores explicit flags.
function withVisibleFlags(content) {
    const tests = content.tests || [];
    const isDict = t => typeof t === 'object' && t !== null;
    const explicit = tests.some(t => isDict(t) && 'visible' in t);
    return {
        ...content,
        tests: tests.map((t, i) => {
            const visible = explicit ? isDict(t) && t.visible === true : i < DEFAULT_VISIBLE_TESTS;
            if (!isDict(t)) return { input: '', expected: t || '', visible };
            return { ...t, input: t.input || '', expected: t.expected || '', visible };
        }),
    };
}

// The main text of each type (rich text in all four): kept on a type change.
const MAIN_TEXT = { TEXT: 'html', QUIZ: 'question', CODE: 'prompt', FILL: 'prompt' };

// The «Тип блока» selector.
const TYPE_CHOICES = [['TEXT', 'Теория'], ['QUIZ', 'Тест'], ['CODE', 'Код'], ['FILL', 'Пропуски']];

// Whether a type change would drop something the author entered (beyond the
// main text, which is kept): options, tests, code, template, explanation.
function hasTypeSpecificContent(type, content) {
    const filled = s => typeof s === 'string' && stripHtml(s) !== '';
    if (type === 'QUIZ') {
        return (content.options || []).some(o => (o || '').trim()) || filled(content.explanation);
    }
    if (type === 'CODE') {
        const starter = (content.starter_code || '').trim();
        return [content.header, content.footer, content.solution].some(s => (s || '').trim())
            || (starter !== '' && starter !== defaultContent('CODE').starter_code.trim())
            || (content.tests || []).some(t => (typeof t === 'string'
                ? t.trim() : (t.input || '').trim() || (t.expected || '').trim()));
    }
    if (type === 'FILL') return (content.template || '').trim() !== '' || filled(content.explanation);
    return false;
}

// "N учеников уже отвечали…", with the right Russian plural.
function answersResetWarning(n) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    const one = mod10 === 1 && mod100 !== 11;
    const few = mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20);
    const who = one ? `${n} ученик уже отвечал` : few ? `${n} ученика уже отвечали` : `${n} учеников уже отвечали`;
    return `${who} на этот блок — ${one ? 'его' : 'их'} результаты по нему будут сброшены.`;
}

function stripHtml(html) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html || '';
    return (tmp.textContent || tmp.innerText || '').trim();
}

// =============================================================================
// Drafts: each editable block has its own draft
// =============================================================================
//
// A draft: { key, id, type, content, baseline, savedType, insertBefore, seq,
// dirty, saving, error }.
// - key: the block id, or "new-<n>" for a block not saved yet (id === null);
//   a new block shows above insertBefore (a block id), or at the end.
// - baseline: JSON of {type, content} as last saved; dirty = differs from it
//   (recomputed on every change, so counting dirty blocks stays cheap).
// - savedType: the stored type (a change resets students' answers).

function draftFromBlock(block) {
    // Deep-ish clone so editing never mutates the server list.
    let content = JSON.parse(JSON.stringify(block.content));
    if (block.type === 'CODE') content = withVisibleFlags(content);
    return {
        key: block.id, id: block.id, type: block.type, content,
        baseline: JSON.stringify({ type: block.type, content }), savedType: block.type,
        insertBefore: null, seq: 0, dirty: false, saving: false, error: '',
    };
}

function newDraft(key, seq, type, insertBefore) {
    const content = defaultContent(type);
    return {
        key, id: null, type, content, baseline: JSON.stringify({ type, content }), savedType: null,
        insertBefore, seq, dirty: false, saving: false, error: '',
    };
}

// The draft with `changes`; `dirty` follows type / content / baseline.
function withChanges(draft, changes) {
    const next = { ...draft, ...changes };
    if ('type' in changes || 'content' in changes || 'baseline' in changes) {
        next.dirty = JSON.stringify({ type: next.type, content: next.content }) !== next.baseline;
    }
    return next;
}

/**
 * The drafts after the block list was (re)loaded from the server. Never
 * overwrites another block's unsaved draft:
 * - a block with a draft keeps it, as it is (dirty or not);
 * - `saved` ({key, block, startedFrom}): the block just saved or created gets
 *   the server's version, unless the author typed on while it was saving:
 *   then her text stays, against the saved version as the new baseline;
 * - a block new on the server (a copy) gets a fresh draft; a deleted one's
 *   draft goes;
 * - new, unsaved blocks stay; one whose anchor block is gone moves to the end.
 */
function mergeDrafts(prev, list, saved = null) {
    const next = {};
    const ids = new Set(list.map(b => b.id));
    for (const block of list) {
        if (saved && block.id === saved.block.id) {
            const fresh = draftFromBlock(saved.block);
            const current = prev[saved.key];
            const typedOn = current
                && JSON.stringify({ type: current.type, content: current.content }) !== saved.startedFrom;
            next[block.id] = typedOn
                ? withChanges({ ...current, key: block.id, id: block.id, savedType: fresh.savedType,
                                insertBefore: null, saving: false, error: '' }, { baseline: fresh.baseline })
                : fresh;
        } else {
            next[block.id] = prev[block.id] || draftFromBlock(block);
        }
    }
    for (const [key, draft] of Object.entries(prev)) {
        if (draft.id !== null || key === saved?.key) continue;
        next[key] = draft.insertBefore && !ids.has(draft.insertBefore) ? { ...draft, insertBefore: null } : draft;
    }
    return next;
}

// "Несохранённые изменения в N блоках…": в 1 / 21 блоке, в 2 / 5 блоках.
function leaveWarning(n) {
    const one = n % 10 === 1 && n % 100 !== 11;
    return `Несохранённые изменения в ${n} ${one ? 'блоке' : 'блоках'}. Уйти без сохранения?`;
}

function validate(type, content) {
    if (type === 'TEXT') {
        if (!stripHtml(content.html)) return 'Добавьте текст теории.';
    } else if (type === 'QUIZ') {
        if (!stripHtml(content.question)) return 'Введите вопрос.';
        const filled = content.options.filter(o => o.trim());
        if (filled.length < 2) return 'Нужно минимум два варианта ответа.';
        if (content.multiple_answers
            ? !content.correct_answers?.length || content.correct_answers.some(i => !content.options[i]?.trim())
            : content.correct_answer == null || !content.options[content.correct_answer]?.trim())
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

// Content as sent to the server: QUIZ options trimmed, empty CODE tests dropped.
function cleanContent(type, content) {
    if (type === 'QUIZ') {
        const kept = content.options.map((text, index) => ({ text: text.trim(), index })).filter(o => o.text);
        const options = kept.map(o => o.text);
        if (content.multiple_answers) {
            const correct_answers = kept.flatMap((o, index) => content.correct_answers.includes(o.index) ? [index] : []);
            const cleaned = { ...content, options, correct_answers };
            delete cleaned.correct_answer;
            return cleaned;
        }
        const correct_answer = kept.findIndex(o => o.index === content.correct_answer);
        const cleaned = { ...content, options, correct_answer };
        delete cleaned.correct_answers;
        return cleaned;
    }
    if (type === 'CODE') {
        const tests = (content.tests || [])
            .filter(t => t.input.trim() !== '' || t.expected.trim() !== '');
        return { ...content, tests };
    }
    return content;
}

function LessonEditor() {
    const { lessonId } = useParams();
    const navigate = useNavigate();
    // ?block=<id> opens only that block; no parameter opens the full lesson.
    const [searchParams] = useSearchParams();
    const selectedBlockId = searchParams.get('block');
    const singleBlockMode = selectedBlockId !== null;

    const [lesson, setLesson] = useState(null);
    const [blocks, setBlocks] = useState([]); // the server's list, in order
    const [drafts, setDrafts] = useState({}); // key → draft (see above)
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [insertMenu, setInsertMenu] = useState(null); // «+ Вставить блок» open above this block id
    const [lastSavedId, setLastSavedId] = useState(null); // "Предпросмотр" returns here
    const [busy, setBusy] = useState(false); // reorder/delete/copy in flight
    const [flashId, setFlashId] = useState(null); // a new copy or a ?block= target, briefly highlighted
    const [copyStatus, setCopyStatus] = useState(''); // for screen readers
    const scrollToRef = useRef(null); // ?block= target, scrolled to once rendered
    const copyingRef = useRef(false); // a double click must not make two copies
    const newSeqRef = useRef(0); // numbers new blocks: keys "new-1", "new-2", …
    const reloadSeqRef = useRef(0); // only the latest block list is shown
    const movingBlockRef = useRef(false);

    // Stable callbacks for the (memoized) cards read the current handlers and
    // state from here. Only to READ: every state change is a functional update.
    const latest = useRef(null);
    useEffect(() => {
        latest.current = { drafts, blocks, handleSave, handleDelete, handleDuplicate, moveBlock };
    });

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [lessonId]);

    // A fresh editor starts at the top («Следующий урок →» keeps the scroll
    // position otherwise); a ?block= target is scrolled to once loaded.
    useEffect(() => {
        window.scrollTo(0, 0);
    }, []);

    // The highlight goes away after a moment.
    useEffect(() => {
        if (!flashId) return undefined;
        const timer = setTimeout(() => setFlashId(null), 2500);
        return () => clearTimeout(timer);
    }, [flashId]);

    // ?block=<id>: scroll to that card once the cards are on the page. The
    // cards above it are still growing while their editors render, so keep it
    // in place until the layout settles (2 s), or the author scrolls herself.
    useEffect(() => {
        const id = scrollToRef.current;
        const el = id && document.getElementById(`edit-block-${id}`);
        if (!el) return undefined;
        scrollToRef.current = null;
        const scroll = () => el.scrollIntoView({ block: 'start' });
        scroll();
        const observer = new ResizeObserver(scroll);
        observer.observe(document.body);
        const userEvents = ['wheel', 'touchstart', 'keydown', 'mousedown'];
        const stop = () => {
            observer.disconnect();
            clearTimeout(timer);
            userEvents.forEach(type => window.removeEventListener(type, stop));
        };
        const timer = setTimeout(stop, 2000);
        userEvents.forEach(type => window.addEventListener(type, stop, { passive: true }));
        return stop;
    }, [loading]);

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
            setDrafts(prev => mergeDrafts(prev, blocksRes.data));

            if (singleBlockMode) {
                if (blocksRes.data.some(b => b.id === selectedBlockId)) {
                    scrollToRef.current = selectedBlockId;
                    setFlashId(selectedBlockId);
                } else {
                    setError('Блок не найден в этом уроке.');
                }
            }
        } catch (err) {
            console.error('Failed to load lesson editor:', err);
            setError('Не удалось загрузить урок.');
        } finally {
            setLoading(false);
        }
    }

    // The list from the server, merged into the drafts (mergeDrafts: other
    // blocks' unsaved drafts are never touched). Several reloads may be in
    // flight (saves of different blocks): an older list is not shown over a
    // newer one, but its saved block's draft is still updated.
    async function reloadBlocks(saved = null) {
        const seq = ++reloadSeqRef.current;
        const res = await api.get(`/blocks/?lesson=${lessonId}`);
        if (seq === reloadSeqRef.current) setBlocks(res.data);
        setDrafts(prev => mergeDrafts(prev, res.data, saved));
    }

    function nextOrderIndex() {
        if (blocks.length === 0) return 1;
        return Math.max(...blocks.map(b => b.order_index)) + 1;
    }

    // A new, unsaved block: at the end, or (insertBefore) above that block.
    function startAdd(type, insertBefore = null) {
        setInsertMenu(null);
        const seq = ++newSeqRef.current;
        const key = `new-${seq}`;
        setDrafts(prev => ({ ...prev, [key]: newDraft(key, seq, type, insertBefore) }));
    }

    const dirtyCount = Object.values(drafts).filter(d => d.dirty).length;

    // Unsaved changes are never lost without asking:
    // - leaving this page inside the app (any link or button, Back / Forward):
    //   useBlocker, including switching between a block and the full editor;
    // - tab close, reload, plain links to Django pages (the header): the
    //   browser's own dialog (beforeunload; browsers don't allow custom text).
    const blocker = useBlocker(({ currentLocation, nextLocation }) =>
        dirtyCount > 0 && (currentLocation.pathname !== nextLocation.pathname
            || new URLSearchParams(currentLocation.search).get('block') !== new URLSearchParams(nextLocation.search).get('block')));

    useEffect(() => {
        if (blocker.state !== 'blocked') return;
        if (window.confirm(leaveWarning(dirtyCount))) {
            blocker.proceed();
        } else {
            blocker.reset();
        }
    }, [blocker, dirtyCount]);

    useEffect(() => {
        if (dirtyCount === 0) return undefined;
        function onBeforeUnload(event) {
            event.preventDefault();
            event.returnValue = ''; // older browsers
        }
        window.addEventListener('beforeunload', onBeforeUnload);
        return () => window.removeEventListener('beforeunload', onBeforeUnload);
    }, [dirtyCount]);

    // Back to the lesson at the last block saved.
    function previewPath() {
        const blockId = lastSavedId || selectedBlockId;
        return blockId ? `/lesson/${lessonId}/#block-${blockId}` : `/lesson/${lessonId}/`;
    }

    // One block's draft, from the previous state; no-op once it's gone.
    function updateDraft(key, fn) {
        setDrafts(prev => (prev[key] ? { ...prev, [key]: fn(prev[key]) } : prev));
    }

    // Saves one block; the others are not touched. Any error, before or after
    // the request, ends in that block's message: a save never fails silently.
    async function handleSave(key) {
        const draft = drafts[key];
        if (!draft || draft.saving || !draft.dirty) return;
        const { id, type } = draft;
        // What this save started from: text typed on meanwhile stays (mergeDrafts).
        const startedFrom = JSON.stringify({ type, content: draft.content });
        updateDraft(key, d => ({ ...d, saving: true, error: '' }));
        try {
            const content = cleanContent(type, draft.content);
            const err = validate(type, content);
            if (err) { updateDraft(key, d => ({ ...d, error: err })); return; }

            // A new type is a different task: the server resets the block's
            // answers. Warn when students (not the author) have any.
            if (id !== null && type !== draft.savedType) {
                const { data } = await api.get(`/blocks/${id}/answered/`);
                if (data.students > 0 && !window.confirm(answersResetWarning(data.students))) return;
            }

            let res;
            if (id === null) {
                const anchor = draft.insertBefore && blocks.some(b => b.id === draft.insertBefore)
                    ? draft.insertBefore : null;
                res = await api.post('/blocks/', {
                    lesson: lessonId,
                    type,
                    order_index: nextOrderIndex(),
                    content,
                    // «+ Вставить блок»: the server puts it in this block's place.
                    ...(anchor ? { insert_before: anchor } : {}),
                });
            } else {
                // PATCH without order_index: a move of another block, in flight
                // at the same time, can't make it stale.
                res = await api.patch(`/blocks/${id}/`, { type, content });
            }
            setLastSavedId(res.data.id);
            await reloadBlocks({ key, block: res.data, startedFrom });
        } catch (e) {
            console.error('Failed to save block:', e);
            const contentErrors = e.response?.data?.content;
            const message = Array.isArray(contentErrors) ? contentErrors.join(' ') : contentErrors;
            updateDraft(key, d => ({ ...d, error: typeof message === 'string' ? message : 'Не удалось сохранить блок. Проверьте поля.' }));
        } finally {
            updateDraft(key, d => ({ ...d, saving: false }));
        }
    }

    async function handleDelete(block) {
        if (!window.confirm('Удалить этот блок?')) return;
        setBusy(true);
        try {
            await api.delete(`/blocks/${block.id}/`);
            await reloadBlocks();
        } catch (e) {
            console.error('Failed to delete block:', e);
            alert('Не удалось удалить блок.');
        } finally {
            setBusy(false);
        }
    }

    // "Копировать": the server copies the SAVED block right below the original
    // and moves the blocks below down by one (one transaction). Mirror that
    // locally: no reload, no scroll jump; the copy gets its own draft.
    async function handleDuplicate(block) {
        if (copyingRef.current) return;
        copyingRef.current = true;
        setBusy(true);
        setCopyStatus('');
        try {
            const res = await api.post(`/blocks/${block.id}/duplicate/`);
            const copy = res.data;
            setBlocks(prev => {
                const i = prev.findIndex(b => b.id === block.id);
                const below = prev.slice(i + 1).map(b => ({ ...b, order_index: b.order_index + 1 }));
                return [...prev.slice(0, i + 1), copy, ...below];
            });
            setDrafts(prev => ({ ...prev, [copy.id]: draftFromBlock(copy) }));
            setFlashId(copy.id);
            setCopyStatus('Блок скопирован, копия ниже.');
        } catch (e) {
            console.error('Failed to copy block:', e);
            alert('Не удалось скопировать блок.');
        } finally {
            copyingRef.current = false;
            setBusy(false);
        }
    }

    async function moveBlock(id, dir) {
        const index = blocks.findIndex(b => b.id === id);
        const target = index + dir;
        if (index < 0 || target < 0 || target >= blocks.length) return;
        return moveBlockTo(id, target + 1);
    }

    async function moveBlockTo(id, position) {
        if (movingBlockRef.current || busy) return;
        movingBlockRef.current = true;
        setBusy(true);
        try {
            await api.post(`/blocks/${id}/reorder/`, { new_order: position });
            await reloadBlocks();
            setCopyStatus(`Блок перемещён на позицию ${position}.`);
        } catch (e) {
            console.error('Failed to reorder blocks:', e);
            alert('Не удалось изменить порядок.');
            await reloadBlocks();
        } finally {
            movingBlockRef.current = false;
            setBusy(false);
        }
    }

    // What the cards call: stable, so typing in one card re-renders only it.
    // Each change is computed from the previous state (functional update);
    // `latest` is only read, to ask before a change or to start a request.
    const actions = useMemo(() => ({
        setContent: (key, updater) => setDrafts(prev => (prev[key]
            ? { ...prev, [key]: withChanges(prev[key], { content: updater(prev[key].content) }) }
            : prev)),
        // «Тип блока»: the new type's defaults, keeping the main text.
        changeType: (key, type) => {
            const current = latest.current.drafts[key];
            if (!current || type === current.type) return;
            if (hasTypeSpecificContent(current.type, current.content)
                && !window.confirm('Сменить тип блока? Варианты ответов, тесты и другие настройки этого типа будут удалены.')) return;
            setDrafts(prev => (prev[key] ? {
                ...prev,
                [key]: withChanges(prev[key], {
                    type,
                    content: { ...defaultContent(type), [MAIN_TEXT[type]]: prev[key].content[MAIN_TEXT[prev[key].type]] || '' },
                    error: '',
                }),
            } : prev));
        },
        // «Отменить изменения»: back to the saved version.
        revert: key => {
            if (!latest.current.drafts[key]?.dirty) return;
            if (!window.confirm('Отменить изменения в этом блоке?')) return;
            setDrafts(prev => {
                if (!prev[key]) return prev;
                const { type, content } = JSON.parse(prev[key].baseline);
                return { ...prev, [key]: withChanges(prev[key], { type, content, error: '' }) };
            });
        },
        // «Убрать»: a new block that was never saved.
        remove: key => {
            if (latest.current.drafts[key]?.dirty && !window.confirm('Убрать новый блок? Введённый текст будет потерян.')) return;
            setDrafts(prev => {
                const next = { ...prev };
                delete next[key];
                return next;
            });
        },
        save: key => latest.current.handleSave(key),
        move: (id, dir) => latest.current.moveBlock(id, dir),
        duplicate: id => latest.current.handleDuplicate(latest.current.blocks.find(b => b.id === id)),
        delete: id => latest.current.handleDelete(latest.current.blocks.find(b => b.id === id)),
    }), []);

    const blockDrag = useDragReorder({
        ids: blocks.map(block => block.id),
        disabled: busy || singleBlockMode || user?.role !== 'AUTHOR',
        onMove: moveBlockTo,
    });

    if (loading) return <p style={{ padding: 40, textAlign: 'center', color: 'var(--color-muted)' }}>Загрузка...</p>;
    if (error) return <p style={{ padding: 40, textAlign: 'center', color: 'var(--color-danger)' }}>{error}</p>;
    if (user?.role !== 'AUTHOR') {
        return <p style={{ padding: 40, textAlign: 'center', color: 'var(--color-danger)' }}>Только автор курса может редактировать урок.</p>;
    }

    // New, unsaved blocks: above their anchor block, or at the end.
    const newDrafts = Object.values(drafts).filter(d => d.id === null).sort((a, b) => a.seq - b.seq);
    const newAbove = id => newDrafts.filter(d => d.insertBefore === id);
    const newAtEnd = newDrafts.filter(d => !d.insertBefore);
    const visibleDrafts = singleBlockMode ? [drafts[selectedBlockId]].filter(Boolean)
        : [...blocks.flatMap(block => [...newAbove(block.id), drafts[block.id]].filter(Boolean)), ...newAtEnd];
    const markerBlocks = visibleDrafts.map((draft, index) => ({
        dirty: draft.dirty,
        elementId: draft.id === null ? `edit-new-${draft.key}` : `edit-block-${draft.id}`,
        label: `Несохранённые изменения: ${TYPE_LABELS[draft.type]}, блок ${index + 1}`,
    }));
    const renderCard = (draft, index = -1) => (
        <BlockCard
            key={draft.key}
            draft={draft}
            actions={actions}
            busy={busy}
            singleBlockMode={singleBlockMode}
            reorderProps={draft.id !== null ? blockDrag.getItemProps(draft.id) : undefined}
            dragHandleProps={draft.id !== null ? blockDrag.getHandleProps(draft.id) : undefined}
            canMoveUp={index > 0}
            canMoveDown={index >= 0 && index < blocks.length - 1}
            flash={flashId !== null && flashId === draft.id}
        />
    );

    if (singleBlockMode) {
        const draft = drafts[selectedBlockId];
        return (
            <div className="page">
                <UnsavedBlockMarkers blocks={markerBlocks} />
                <button className="btn btn-ghost btn-sm page__back" onClick={() => navigate(previewPath())}>
                    ← Назад к уроку
                </button>
                <div style={{ fontSize: 13, color: 'var(--color-muted)' }}>Редактор блока · Урок {lesson.lesson_position}</div>
                <h2>{lesson.title}</h2>
                {draft ? renderCard(draft) : <p role="alert">Блок не найден в этом уроке.</p>}
            </div>
        );
    }

    return (
        <div className="page">
            <UnsavedBlockMarkers blocks={markerBlocks} />
            <button className="btn btn-ghost btn-sm page__back" onClick={() => navigate(`/courses/${lesson.course}/`)}>
                ← Назад к курсу
            </button>

            <div>
                <div>
                    {/* Position in the course, as on the course page (not order_index). */}
                    <div style={{ fontSize: 13, color: 'var(--color-muted)' }}>Редактор урока {lesson.lesson_position}</div>
                    <EditableTitle
                        as="h2"
                        value={lesson.title}
                        canEdit
                        onSave={async title => {
                            const res = await api.patch(`/lessons/${lessonId}/`, { title });
                            setLesson(prev => ({ ...prev, title: res.data.title }));
                        }}
                    />
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 'var(--space-4)' }}>
                    <PreviousLessonButton previousLessonId={lesson.previous_lesson_id} />
                    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 8, marginLeft: 'auto' }}>
                        <button onClick={() => navigate(previewPath())} style={ghostBtn}>
                            👁 Предпросмотр
                        </button>
                        <NextLessonButton nextLessonId={lesson.next_lesson_id} />
                    </div>
                </div>
            </div>
            <hr style={{ margin: '20px 0' }} />
            <p className="visually-hidden" role="status">{copyStatus}</p>

            {blocks.length === 0 && newDrafts.length === 0 && (
                <p style={{ color: 'var(--color-muted)' }}>В этом уроке пока нет блоков. Добавьте первый блок ниже.</p>
            )}

            {/* Every block open for editing. Above each: «+ Вставить блок» and
                the new blocks inserted there. */}
            {blocks.map((block, index) => drafts[block.id] && (
                <Fragment key={block.id}>
                    <InsertControl
                        open={insertMenu === block.id}
                        onOpen={() => setInsertMenu(block.id)}
                        onPick={type => startAdd(type, block.id)}
                        onCancel={() => setInsertMenu(null)}
                    />
                    {newAbove(block.id).map(draft => renderCard(draft))}
                    {renderCard(drafts[block.id], index)}
                </Fragment>
            ))}

            {newAtEnd.map(draft => renderCard(draft))}

            {/* Add block buttons */}
            <div style={{ marginTop: 24, padding: 16, border: '1px dashed var(--color-line)', borderRadius: 8, background: 'var(--color-soft)' }}>
                <div style={{ fontWeight: 600, marginBottom: 10, color: 'var(--color-ink)' }}>Добавить блок:</div>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    {['TEXT', 'QUIZ', 'CODE', 'FILL'].map(type => (
                        <button key={type} onClick={() => startAdd(type)} style={addBtn}>
                            {TYPE_LABELS[type]}
                        </button>
                    ))}
                </div>
            </div>

            {/* Repeat lesson navigation after the blocks. */}
            {(lesson.previous_lesson_id || lesson.next_lesson_id) && (
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 16 }}>
                    <PreviousLessonButton previousLessonId={lesson.previous_lesson_id} />
                    {lesson.next_lesson_id && (
                        <div style={{ marginLeft: 'auto' }}>
                            <NextLessonButton nextLessonId={lesson.next_lesson_id} />
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// «Следующий урок →»: the next lesson's editor. next_lesson_id is the lesson
// page's own "next" (GET /api/lessons/<id>/); none on the last lesson.
// Unsaved changes ask first (useBlocker in LessonEditor).
function PreviousLessonButton({ previousLessonId }) {
    const navigate = useNavigate();
    if (!previousLessonId) return null;
    return (
        <button onClick={() => navigate(`/lesson/${previousLessonId}/edit/`)} style={ghostBtn}>
            ← Предыдущий урок
        </button>
    );
}

function NextLessonButton({ nextLessonId }) {
    const navigate = useNavigate();
    if (!nextLessonId) return null;
    return (
        <button onClick={() => navigate(`/lesson/${nextLessonId}/edit/`)} style={ghostBtn}>
            Следующий урок →
        </button>
    );
}

// =============================================================================
// BLOCK CARD (per-type fields)
// =============================================================================

// «+ Вставить блок» above a block: a slim muted line until clicked, then the
// four type buttons right there.
function InsertControl({ open, onOpen, onPick, onCancel }) {
    if (!open) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 4, marginBottom: -8 }}>
                <button onClick={onOpen} style={insertBtn}>+ Вставить блок</button>
            </div>
        );
    }
    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 12, padding: 12, border: '1px dashed var(--color-line)', borderRadius: 8, background: 'var(--color-soft)' }}>
            <span style={{ fontWeight: 600, color: 'var(--color-ink)' }}>Вставить здесь:</span>
            {['TEXT', 'QUIZ', 'CODE', 'FILL'].map(type => (
                <button key={type} onClick={() => onPick(type)} style={addBtn}>
                    {TYPE_LABELS[type]}
                </button>
            ))}
            <button onClick={onCancel} style={ghostBtn}>Отмена</button>
        </div>
    );
}

// One block, always open for editing. Memoized: it re-renders only when its
// own draft (or busy / position / highlight) changes, not when another block
// is typed in.
const BlockCard = memo(function BlockCard({ draft, actions, busy, canMoveUp, canMoveDown, flash, singleBlockMode = false, reorderProps, dragHandleProps }) {
    const { key, id, type, content, dirty, saving, error } = draft;
    const isNew = id === null;
    const setContent = useCallback(updater => actions.setContent(key, updater), [actions, key]);

    return (
        // scroll-margin: ?block= scrolls the card clear of the sticky app header.
        <div
            {...reorderProps}
            id={isNew ? `edit-new-${key}` : `edit-block-${id}`}
            tabIndex={-1}
            style={{
                ...blockCard,
                borderLeft: `4px solid ${dirty ? 'var(--color-warning)' : 'var(--color-success-on-light)'}`,
                scrollMarginTop: 'calc(var(--space-8) + var(--space-4))',
                ...(flash ? copiedCard : null),
            }}
        >
            {/* Wraps on narrow screens. */}
            <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 14 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
                    <span style={badge}>{isNew ? 'Новый блок: ' : ''}{TYPE_LABELS[type]}</span>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, color: 'var(--color-ink)', fontWeight: 600 }}>
                        Тип блока
                        <select value={type} onChange={e => actions.changeType(key, e.target.value)} style={{ ...input, width: 'auto' }}>
                            {TYPE_CHOICES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                    </label>
                </div>
                {!isNew && !singleBlockMode && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        <DragHandle {...dragHandleProps} />
                        <button title="Вверх" disabled={busy || !canMoveUp} onClick={() => actions.move(id, -1)} style={iconBtn}>↑</button>
                        <button title="Вниз" disabled={busy || !canMoveDown} onClick={() => actions.move(id, 1)} style={iconBtn}>↓</button>
                        <button
                            disabled={busy}
                            onClick={() => actions.duplicate(id)}
                            style={iconBtn}
                            title={dirty
                                ? 'Копируется сохранённая версия блока, без несохранённых изменений. Копия появится ниже.'
                                : 'Копируется сохранённая версия блока. Копия появится ниже.'}
                        >⧉ Копировать</button>
                        <button disabled={busy} onClick={() => actions.delete(id)} style={deleteBtn}>Удалить</button>
                    </div>
                )}
            </div>

            {type === 'TEXT' && (
                <Field label="Текст теории">
                    <RichField field="html" value={content.html} setContent={setContent} placeholder="Напишите теорию урока..."
                        headingLevels={TEXT_HEADING_LEVELS} />
                </Field>
            )}

            {type === 'QUIZ' && <QuizFields uid={key} content={content} setContent={setContent} />}

            {type === 'CODE' && <CodeFields content={content} setContent={setContent} />}

            {type === 'FILL' && <FillFields content={content} setContent={setContent} />}

            {error && <p style={{ color: 'var(--color-danger)', marginTop: 8 }}>{error}</p>}

            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginTop: 16 }}>
                <button
                    onClick={() => actions.save(key)}
                    disabled={!dirty || saving}
                    style={{ ...saveBtn, ...(!dirty || saving ? disabledBtn : null) }}
                >
                    {saving ? 'Сохранение...' : 'Сохранить'}
                </button>
                {isNew ? (
                    <button onClick={() => actions.remove(key)} disabled={saving} style={ghostBtn}>Убрать</button>
                ) : (
                    <button
                        onClick={() => actions.revert(key)}
                        disabled={!dirty || saving}
                        style={{ ...ghostBtn, ...(!dirty || saving ? disabledBtn : null) }}
                    >Отменить изменения</button>
                )}
                <span style={{ fontSize: 13, color: dirty ? 'var(--color-warning)' : 'var(--color-muted)' }} aria-live="polite">
                    {dirty ? 'Есть изменения' : isNew ? 'Новый блок — не сохранён' : 'Сохранено'}
                </span>
            </div>
        </div>
    );
});

function QuizFields({ uid, content, setContent }) {
    return (
        <>
            <Field label="Вопрос" hint="Используйте «Код-блок» для кода и кнопку «Картинка» для изображений и формул.">
                <RichField field="question" value={content.question} setContent={setContent} placeholder="Что выведет этот код?" />
            </Field>

            <Field label="Варианты ответа" hint={content.multiple_answers ? 'Отметьте все правильные варианты. Для зачёта нужно выбрать их все.' : 'Отметьте кружком правильный вариант.'}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                    <input
                        type="checkbox"
                        checked={content.multiple_answers === true}
                        onChange={e => {
                            const multiple_answers = e.target.checked;
                            setContent(c => ({ ...c, multiple_answers,
                                correct_answers: multiple_answers ? (c.correct_answer == null ? [] : [c.correct_answer]) : c.correct_answers,
                                correct_answer: multiple_answers ? c.correct_answer : (c.correct_answers?.[0] ?? 0),
                            }));
                        }}
                    />
                    Несколько правильных ответов
                </label>
                {content.options.map((opt, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <input
                            type={content.multiple_answers ? 'checkbox' : 'radio'}
                            name={`correct-${uid}`}
                            checked={content.multiple_answers ? (content.correct_answers || []).includes(i) : content.correct_answer === i}
                            onChange={() => setContent(c => c.multiple_answers
                                ? { ...c, correct_answers: (c.correct_answers || []).includes(i)
                                    ? c.correct_answers.filter(index => index !== i) : [...(c.correct_answers || []), i] }
                                : { ...c, correct_answer: i })}
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
                                const correct_answers = (c.correct_answers || [])
                                    .filter(index => index !== i).map(index => index > i ? index - 1 : index);
                                return { ...c, options, correct_answer, correct_answers };
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
                <BulkOptions setContent={setContent} />
                {/* Missing in older quizzes = on. */}
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, fontSize: 14, color: 'var(--color-ink)' }}>
                    <input
                        type="checkbox"
                        checked={content.shuffle_options !== false}
                        onChange={e => setContent(c => ({ ...c, shuffle_options: e.target.checked }))}
                    />
                    Перемешивать варианты ответа
                </label>
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

// Turns pasted text into quiz options: one non-empty line = one option.
// A line starting with "* " (asterisk + space) is marked as the correct answer;
// "*args" without a space stays a normal option.
// Returns { options, correct } where correct contains the marked indices.
function parseBulkOptions(text) {
    const options = [];
    const correct = [];
    for (const raw of text.split(/\r?\n/)) {
        let line = raw.trim();
        if (!line) continue;
        const marked = /^\*\s+/.test(line);
        if (marked) {
            line = line.replace(/^\*\s+/, '');
            correct.push(options.length);
        }
        options.push(line);
    }
    return { options, correct };
}

function BulkOptions({ setContent }) {
    const [open, setOpen] = useState(false);
    const [text, setText] = useState('');
    const [note, setNote] = useState('');
    const { options, correct } = parseBulkOptions(text);

    const apply = (mode) => {
        if (options.length === 0) return;
        setContent(c => {
            const keptIndices = mode === 'append' ? c.options.flatMap((text, index) => text.trim() ? [index] : []) : [];
            const kept = keptIndices.map(index => c.options[index]);
            const next = [...kept, ...options];
            while (next.length < 2) next.push('');
            if (c.multiple_answers) {
                const keptCorrect = keptIndices.flatMap((original, index) => (c.correct_answers || []).includes(original) ? [index] : []);
                return { ...c, options: next,
                    correct_answers: [...keptCorrect, ...correct.map(index => kept.length + index)] };
            }
            let correct_answer;
            if (correct.length) correct_answer = kept.length + correct[0];
            else if (mode === 'append' && c.options[c.correct_answer]?.trim())
                correct_answer = keptIndices.indexOf(c.correct_answer);
            else correct_answer = 0;
            return { ...c, options: next, correct_answer: Math.max(0, correct_answer) };
        });
        setNote(correct.length
            ? `Добавлено вариантов: ${options.length}. Правильные ответы отмечены с учётом режима теста.`
            : `Добавлено вариантов: ${options.length}. Отметьте правильные ответы.`);
        setText('');
    };

    if (!open) {
        return (
            <button
                type="button"
                onClick={() => { setOpen(true); setNote(''); }}
                style={{ ...ghostBtn, padding: '6px 12px', marginLeft: 8 }}
            >📋 Вставить списком</button>
        );
    }

    return (
        <div style={{ marginTop: 12, padding: 12, border: '1px dashed var(--color-line)', borderRadius: 8, background: 'var(--color-soft)' }}>
            <div style={{ fontSize: 12, color: 'var(--color-muted)', marginBottom: 8 }}>
                Каждый вариант — с новой строки. Пустые строки пропускаются.
                Начните строку с <b>*&nbsp;</b> (звёздочка и пробел), чтобы сразу отметить правильный ответ.
            </div>
            <textarea
                value={text}
                onChange={e => setText(e.target.value)}
                rows={6}
                autoFocus
                placeholder={'True\n* False\nNone\nTypeError'}
                style={{ ...input, fontFamily: "'JetBrains Mono', Consolas, monospace", resize: 'vertical' }}
            />
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <button type="button" onClick={() => apply('replace')} disabled={!options.length} style={{ ...saveBtn, padding: '6px 14px' }}>
                    Заменить варианты{options.length ? ` (${options.length})` : ''}
                </button>
                <button type="button" onClick={() => apply('append')} disabled={!options.length} style={{ ...ghostBtn, padding: '6px 14px' }}>
                    Добавить к имеющимся
                </button>
                <button type="button" onClick={() => { setOpen(false); setText(''); }} style={{ ...iconBtn }}>
                    Свернуть
                </button>
                {note && <span style={{ fontSize: 12, color: 'var(--color-success-on-light)' }}>{note}</span>}
            </div>
        </div>
    );
}

function CodeFields({ content, setContent }) {
    const comparison = OUTPUT_COMPARISONS.find(option => option.value === (content.output_comparison ?? 'exact'));
    return (
        <>
            <Field label="Условие задачи">
                <RichField field="prompt" value={content.prompt} setContent={setContent} placeholder="Опишите, что нужно сделать..." />
            </Field>

            <Field label="Скрытый код ДО решения (HEADER)" hint="Выполняется перед кодом ученика. Ученик его не видит: импорты, классы, данные.">
                <CodeField field="header" value={content.header || ''} setContent={setContent} />
            </Field>

            <Field label="Стартовый код">
                <CodeField field="starter_code" value={content.starter_code} setContent={setContent} />
            </Field>

            <Field
                label="Скрытый код ПОСЛЕ решения (FOOTER)"
                hint={<>
                    Выполняется после кода ученика. Ученик его не видит: вызовы функций, вывод для тестов.<br />
                    Кнопка «Запустить» использует сохранённый HEADER/FOOTER — сохраните блок перед проверкой.
                </>}
            >
                <CodeField field="footer" value={content.footer || ''} setContent={setContent} />
            </Field>

            <Field label="Решение (необязательно, студентам не показывается)">
                <CodeField field="solution" value={content.solution || ''} setContent={setContent} />
            </Field>

            <Field label="Проверка вывода" hint={comparison?.hint}>
                <select
                    aria-label="Проверка вывода"
                    value={content.output_comparison ?? 'exact'}
                    onChange={e => setContent(c => ({ ...c, output_comparison: e.target.value }))}
                    style={input}
                >
                    {OUTPUT_COMPARISONS.map(option => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                </select>
                <div style={{ fontSize: 12, color: 'var(--color-muted)', marginTop: 8 }}>
                    Режим применяется ко всем тестам этой задачи, включая скрытые. Сохраните блок перед проверкой.
                </div>
            </Field>

            <Field label="Тесты" hint="Ввод подаётся в stdin, ожидаемый вывод сравнивается со stdout. Пустые тесты игнорируются. Решение проверяется на всех тестах; ученик видит только отмеченные «Показывать ученику», об остальных — лишь «пройден / не пройден».">
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
                        <label
                            style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: 'var(--color-muted)', whiteSpace: 'nowrap', paddingTop: 12 }}
                            title="Видимые тесты ученик видит целиком; скрытые — только «пройден / не пройден»"
                        >
                            <input
                                type="checkbox"
                                checked={test.visible === true}
                                onChange={e => setContent(c => {
                                    const tests = [...c.tests];
                                    tests[i] = { ...tests[i], visible: e.target.checked };
                                    return { ...c, tests };
                                })}
                            />
                            Показывать ученику
                        </label>
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
                    onClick={() => setContent(c => ({
                        ...c,
                        // New tests follow the default: the first two are shown to students.
                        tests: [...(c.tests || []), { input: '', expected: '', visible: (c.tests || []).length < DEFAULT_VISIBLE_TESTS }],
                    }))}
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
                <RichField
                    field="prompt"
                    value={content.prompt}
                    setContent={setContent}
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
                    style={{ ...input, minHeight: 70, fontFamily: "'JetBrains Mono', Consolas, monospace", fontVariantLigatures: 'none', fontFeatureSettings: '"liga" 0, "calt" 0' }}
                    placeholder="print({{8}})"
                />
            </Field>

            {/* Live preview of how the blanks will look + which answers are accepted */}
            {hasBlanks && (
                <Field label="Предпросмотр">
                    <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 2.2, fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 14, color: 'var(--color-ink)', fontVariantLigatures: 'none', fontFeatureSettings: '"liga" 0, "calt" 0' }}>
                        {segments.map((seg, idx) => (
                            seg.type === 'text'
                                ? <span key={idx}>{seg.value}</span>
                                : <span key={idx} style={previewBlank} title="Принимаемые ответы">{seg.answers.join(' / ') || '⌀'}</span>
                        ))}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--color-muted)', marginTop: 8 }}>
                        В пропусках показаны принимаемые ответы — студент увидит пустые поля.
                    </div>
                </Field>
            )}

            <Field label="">
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, color: 'var(--color-ink)' }}>
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

// The rich-text and code fields of a card: memoized, with a stable onChange
// per field, so typing elsewhere in the card doesn't re-render them, and
// @uiw/react-codemirror (which reconfigures the whole editor whenever its
// onChange prop changes) never reconfigures while the author types.
const RichField = memo(function RichField({ field, value, setContent, placeholder, headingLevels }) {
    const onChange = useCallback(html => setContent(c => ({ ...c, [field]: html })), [field, setContent]);
    return <RichTextEditor value={value} onChange={onChange} placeholder={placeholder} headingLevels={headingLevels} />;
});

// Theory text gets its own main heading (H1); other rich fields keep H2/H3.
const TEXT_HEADING_LEVELS = [1, 2, 3];

const CodeField = memo(function CodeField({ field, value, setContent }) {
    const onChange = useCallback(val => setContent(c => ({ ...c, [field]: val })), [field, setContent]);
    return (
        <div style={cmWrap}>
            <CodeMirror value={value} height="120px" theme="none" extensions={PY_EXTENSIONS} onChange={onChange} />
        </div>
    );
});

function Field({ label, hint, children }) {
    return (
        <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontWeight: 600, marginBottom: 6, color: 'var(--color-ink)', fontSize: 14 }}>{label}</label>
            {hint && <div style={{ fontSize: 12, color: 'var(--color-muted)', marginBottom: 8 }}>{hint}</div>}
            {children}
        </div>
    );
}

// =============================================================================
// Inline styles
// =============================================================================

// One extensions array for every code editor: a new array on each render
// would make CodeMirror reconfigure itself whenever its card re-renders.
const PY_EXTENSIONS = [python(), pycharmDarcula];

const blockCard = {
    border: '1px solid var(--color-line)',
    borderRadius: 8,
    padding: 16,
    marginTop: 12,
    background: 'var(--color-surface)',
};

// A fresh copy, for a moment (tokens: backend/static/public/css/tokens.css).
const copiedCard = {
    background: 'var(--color-soft)',
    boxShadow: '0 0 0 var(--focus-ring-width) var(--color-accent)',
};

const badge = {
    display: 'inline-block',
    padding: '3px 10px',
    background: 'var(--color-success-soft)',
    color: 'var(--color-success-on-light)',
    borderRadius: 999,
    fontWeight: 600,
    fontSize: 13,
};

const input = {
    width: '100%',
    padding: '8px 10px',
    border: '1px solid var(--color-line)',
    borderRadius: 6,
    fontSize: 14,
    boxSizing: 'border-box',
};

const cmWrap = {
    border: '1px solid var(--color-line)',
    borderRadius: 6,
    overflow: 'hidden',
};

const saveBtn = {
    padding: '9px 22px', background: 'var(--color-success-on-light)', color: 'var(--color-ground)',
    border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
};

const ghostBtn = {
    padding: '9px 18px', background: 'var(--color-surface)', color: 'var(--color-ink)',
    border: '1px solid var(--color-line)', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
};

const addBtn = {
    padding: '10px 18px', background: 'var(--color-surface)', color: 'var(--color-success-on-light)',
    border: '1px solid var(--color-success-on-light)', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
};

// «+ Вставить блок»: quiet, so a long block list stays easy to scan.
const insertBtn = {
    padding: '2px 10px', background: 'none', color: 'var(--color-muted)',
    border: 'none', cursor: 'pointer', fontSize: 12,
};

// «Сохранить» / «Отменить изменения» with nothing to save.
const disabledBtn = { opacity: 0.45, cursor: 'not-allowed' };

const iconBtn = {
    padding: '6px 10px', background: 'var(--color-surface)', color: 'var(--color-muted)',
    border: '1px solid var(--color-line)', borderRadius: 6, cursor: 'pointer', fontSize: 13,
};

const deleteBtn = {
    padding: '6px 12px', background: 'var(--color-surface)', color: 'var(--color-danger)',
    border: '1px solid var(--color-danger)', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 500,
};

const previewBlank = {
    display: 'inline-block', verticalAlign: 'middle',
    fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 14,
    background: 'var(--color-success-soft)', border: '2px solid var(--color-success-on-light)', borderRadius: 999,
    padding: '2px 12px', color: 'var(--color-success-on-light)', fontWeight: 600,
};

// Remount when the lesson or selected block changes so drafts stay within
// the editor that created them. useBlocker protects unsaved changes.
function LessonEditorPage() {
    const { lessonId } = useParams();
    const [searchParams] = useSearchParams();
    const blockId = searchParams.get('block');
    return <LessonEditor key={JSON.stringify([lessonId, blockId])} />;
}

export default LessonEditorPage;
