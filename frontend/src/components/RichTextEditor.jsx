import { useEffect, useRef, useState } from 'react';
import { useEditor, useEditorState, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import { TableKit } from '@tiptap/extension-table';
import TextAlign from '@tiptap/extension-text-align';
import { BlockMath, InlineMath } from '@tiptap/extension-mathematics';
import 'katex/dist/katex.min.css';
import api from '../api';
import FormulaDialog from './FormulaDialog';
import './RichTextEditor.css';

/**
 * WYSIWYG editor for TEXT block / CODE prompt HTML.
 *
 * The teacher edits visually (no HTML knowledge needed); we persist the
 * generated HTML via onChange. TipTap's codeBlock renders as <pre><code>,
 * which TextBlock already syntax-highlights with highlight.js.
 *
 * Images (incl. formulas pasted as pictures) are uploaded to Django via
 * POST /api/upload-image/ and inserted as <img src="<absolute url>">. Authors
 * can add them three ways: the toolbar button, Ctrl+V paste, and drag-and-drop.
 * A selected image can be resized: drag a corner handle (the proportions are
 * kept), or use the image row of the toolbar (smaller / larger / original
 * size). The size is saved as width/height attributes on the <img>; the lesson
 * view keeps height auto and max-width 100%, so it never outgrows the column.
 *
 * Alignment: paragraphs and headings can be centred or set to the right
 * (saved as style="text-align: …"); left is the default, so «По левому краю»
 * removes the style. No justify: without hyphenation Russian text gets wide
 * gaps on phones.
 *
 * Formulas (LaTeX, drawn by KaTeX): «∑ Формула» opens FormulaDialog, with a
 * live preview; selected text becomes the formula. A formula sits inside the
 * line or on a line of its own, centred or at the left. Clicking a formula
 * opens it again to change, move or delete it. Saved as an empty
 * <span data-type="inline-math"> or <div data-type="block-math"> with the
 * formula in data-latex (and data-align="left" for one at the left); the
 * lesson view draws it (lib/contentMath.js).
 *
 * Tables: the toolbar button inserts a 3×3 table with a header row; while the
 * cursor is in a table, a second toolbar row adds and removes rows and columns.
 * Tab moves to the next cell (and adds a row at the end). Columns take the
 * width of their content (no drag-resizing, so no fixed widths are saved).
 *
 * headingLevels: which heading buttons the toolbar shows (H1 only in the TEXT
 * block form). The schema keeps all six levels in every editor, so existing
 * headings in saved content are never rewritten.
 */
const DEFAULT_HEADING_LEVELS = [2, 3];

// Smallest width an image can be shrunk to, px (handles and buttons).
const MIN_IMAGE_WIDTH = 40;

// Tiptap's resizable image view keeps the size it was dragged to even when the
// node changes under it (undo, redo, the size buttons): re-apply the node's size.
const ResizableImage = Image.extend({
    addNodeView() {
        const create = this.parent?.();
        if (!create) return null;
        return props => {
            const view = create(props);
            const update = view.update.bind(view);
            view.update = (node, ...rest) => {
                if (!update(node, ...rest)) return false;
                const { width, height } = node.attrs;
                view.element.style.width = width ? `${width}px` : '';
                view.element.style.height = height ? `${height}px` : '';
                return true;
            };
            return view;
        };
    },
});

// A formula on a line of its own, centred (no attribute, as before) or at the
// left: data-align="left". Tiptap's view doesn't copy attributes to the editor
// DOM, so the view sets it; a changed attribute redraws the view.
const AlignedBlockMath = BlockMath.extend({
    addAttributes() {
        return {
            ...this.parent?.(),
            align: {
                default: null,
                parseHTML: el => (el.getAttribute('data-align') === 'left' ? 'left' : null),
                renderHTML: attrs => (attrs.align ? { 'data-align': attrs.align } : {}),
            },
        };
    },
    addNodeView() {
        const create = this.parent?.();
        if (!create) return null;
        return props => {
            const view = create(props);
            if (props.node.attrs.align) view.dom.setAttribute('data-align', props.node.attrs.align);
            return view;
        };
    },
});

// Where a formula is (FormulaDialog's place) → its node type and attributes.
function formulaNode(latex, place) {
    if (place === 'inline') return { type: 'inlineMath', attrs: { latex } };
    return { type: 'blockMath', attrs: { latex, align: place === 'left' ? 'left' : null } };
}

const HEADING_TITLES = { 1: 'Главный заголовок', 2: 'Заголовок', 3: 'Подзаголовок' };

const ALIGN_BUTTONS = [
    { align: 'left', title: 'По левому краю (Ctrl+Shift+L)' },
    { align: 'center', title: 'По центру (Ctrl+Shift+E)' },
    { align: 'right', title: 'По правому краю (Ctrl+Shift+R)' },
];

// Word-style alignment icon: four lines, short ones placed by `align`.
function AlignIcon({ align }) {
    const lines = [14, 9, 14, 9];
    return (
        <svg width="14" height="12" viewBox="0 0 14 12" aria-hidden="true" style={{ display: 'block', margin: '3px 0' }}>
            {lines.map((w, i) => {
                const x = align === 'center' ? (14 - w) / 2 : align === 'right' ? 14 - w : 0;
                return <rect key={i} x={x} y={i * 3 + 0.25} width={w} height="1.5" rx="0.75" fill="currentColor" />;
            })}
        </svg>
    );
}

function RichTextEditor({ value, onChange, placeholder, headingLevels = DEFAULT_HEADING_LEVELS }) {
    const fileInputRef = useRef(null);
    // The open formula dialog: { latex, place, editing, pos?, range? } or null.
    const [formula, setFormula] = useState(null);

    // An existing formula (clicked, so `node` and `pos`), or a new one at the
    // cursor; selected text, if any, becomes the new formula and is replaced.
    function openFormula({ node, pos }) {
        if (node) {
            const place = node.type.name === 'inlineMath' ? 'inline' : node.attrs.align === 'left' ? 'left' : 'center';
            setFormula({ latex: node.attrs.latex, place, editing: true, pos });
            return;
        }
        const { from, to, empty } = editor.state.selection;
        const text = empty ? '' : editor.state.doc.textBetween(from, to, ' ');
        setFormula({ latex: text, place: 'inline', editing: false, range: text ? { from, to } : null });
    }

    function closeFormula() {
        setFormula(null);
        editor?.commands.focus();
    }

    function submitFormula(latex, place) {
        const content = formulaNode(latex, place);
        const chain = editor.chain().focus();
        if (!formula.editing) {
            chain.insertContentAt(formula.range || editor.state.selection.from, content).run();
        } else {
            const node = editor.state.doc.nodeAt(formula.pos);
            if (node?.type.name === content.type) {
                chain.command(({ tr }) => {
                    tr.setNodeMarkup(formula.pos, undefined, { ...node.attrs, ...content.attrs });
                    return true;
                }).run();
            } else if (node) {
                // Moved between the line and a line of its own: a formula from
                // a line of its own needs a paragraph around it to sit inside a line.
                const replacement = place === 'inline' ? { type: 'paragraph', content: [content] } : content;
                chain.insertContentAt({ from: formula.pos, to: formula.pos + node.nodeSize }, replacement).run();
            }
        }
        setFormula(null);
    }

    function deleteFormula() {
        const node = editor.state.doc.nodeAt(formula.pos);
        if (node) editor.chain().focus().deleteRange({ from: formula.pos, to: formula.pos + node.nodeSize }).run();
        setFormula(null);
    }

    const editor = useEditor({
        extensions: [
            StarterKit,
            ResizableImage.configure({
                inline: false,
                allowBase64: false,
                resize: {
                    enabled: true,
                    directions: ['top-left', 'top-right', 'bottom-left', 'bottom-right'],
                    minWidth: MIN_IMAGE_WIDTH,
                    minHeight: 20,
                    alwaysPreserveAspectRatio: true,
                },
            }),
            TableKit.configure({ table: { resizable: false } }),
            TextAlign.configure({ types: ['heading', 'paragraph'], alignments: ['left', 'center', 'right'] }),
            // Configured one by one: the Mathematics bundle gives both the same
            // KaTeX options, and a formula on its own line needs displayMode
            // (large, centred), as in the lesson view.
            InlineMath.configure({
                katexOptions: { throwOnError: false },
                onClick: (node, pos) => openFormula({ node, pos }),
            }),
            AlignedBlockMath.configure({
                katexOptions: { throwOnError: false, displayMode: true },
                onClick: (node, pos) => openFormula({ node, pos }),
            }),
        ],
        content: value || '',
        // Avoid SSR hydration warnings; harmless on the client.
        immediatelyRender: false,
        editorProps: {
            // Screenshot/clipboard image paste: upload the blob, insert the URL.
            // Returning false for non-image pastes lets TipTap handle normal
            // content (including remote <img> URLs inside pasted HTML).
            handlePaste: (_view, event) => {
                const file = firstImageFile(event.clipboardData?.files);
                if (!file) return false;
                event.preventDefault();
                uploadAndInsert(file);
                return true;
            },
            handleDrop: (_view, event) => {
                const file = firstImageFile(event.dataTransfer?.files);
                if (!file) return false;
                event.preventDefault();
                uploadAndInsert(file);
                return true;
            },
        },
        onUpdate: ({ editor }) => {
            const html = editor.getHTML();
            // TipTap emits "<p></p>" for an empty doc — normalise to "".
            onChange(html === '<p></p>' ? '' : html);
        },
    });

    // Sync external value changes (e.g. switching which block is being edited)
    // without clobbering the user's in-progress typing.
    useEffect(() => {
        if (!editor) return;
        const current = editor.getHTML();
        const incoming = value || '';
        if (incoming !== current && incoming !== (current === '<p></p>' ? '' : current)) {
            editor.commands.setContent(incoming, { emitUpdate: false });
        }
    }, [value, editor]);

    // The toolbar re-renders on edits only; this re-renders it when the cursor
    // moves into or out of a table, an image is selected or the cursor lands
    // in text aligned differently, so rows and the alignment buttons follow a click.
    const { inTable, imageSelected, align } = useEditorState({
        editor,
        selector: ({ editor }) => ({
            inTable: !!editor?.isActive('table'),
            imageSelected: !!editor?.isActive('image'),
            align: editor?.isActive({ textAlign: 'center' }) ? 'center'
                : editor?.isActive({ textAlign: 'right' }) ? 'right' : 'left',
        }),
    });

    // Left is the default: it removes the alignment; centre/right toggle back to it.
    function setAlign(value) {
        const chain = editor.chain().focus();
        if (value === 'left' || value === align) chain.unsetTextAlign().run();
        else chain.setTextAlign(value).run();
    }

    // The selected image's size buttons: scale its shown width by `factor`
    // (between MIN_IMAGE_WIDTH and the editor's text width), or null = the
    // picture's own size again.
    function resizeSelectedImage(factor) {
        if (factor === null) {
            editor.chain().focus().updateAttributes('image', { width: null, height: null }).run();
            return;
        }
        const img = editor.view.nodeDOM(editor.state.selection.from)?.querySelector?.('img');
        if (!img || !img.offsetWidth || !img.offsetHeight) return;
        const page = editor.view.dom;
        const style = getComputedStyle(page);
        const maxWidth = page.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        const width = Math.round(Math.min(maxWidth, Math.max(MIN_IMAGE_WIDTH, img.offsetWidth * factor)));
        const height = Math.round(width * img.offsetHeight / img.offsetWidth);
        editor.chain().focus().updateAttributes('image', { width, height }).run();
    }

    function firstImageFile(fileList) {
        if (!fileList || !fileList.length) return null;
        return Array.from(fileList).find(f => f.type.startsWith('image/')) || null;
    }

    async function uploadAndInsert(file) {
        try {
            const form = new FormData();
            form.append('image', file);
            // Let axios set the multipart Content-Type (with boundary) itself.
            const res = await api.post('/upload-image/', form);
            editor?.chain().focus().setImage({ src: res.data.url }).run();
        } catch (err) {
            console.error('Image upload failed:', err);
            alert('Не удалось загрузить изображение. Поддерживаются PNG/JPG/GIF/WEBP/SVG до 5 МБ.');
        }
    }

    function handleFilePick(e) {
        const file = e.target.files?.[0];
        if (file) uploadAndInsert(file);
        e.target.value = ''; // allow re-selecting the same file
    }

    if (!editor) return null;

    const btn = (active) => ({
        padding: '4px 10px',
        border: '1px solid var(--color-line)',
        borderRadius: '6px',
        background: active ? 'var(--color-success-on-light)' : 'var(--color-ground)',
        color: active ? 'var(--color-ground)' : 'var(--color-ink)',
        cursor: 'pointer',
        fontSize: '13px',
        fontWeight: 600,
        lineHeight: 1.4,
    });

    const stepBtn = (enabled) => ({
        ...btn(false),
        opacity: enabled ? 1 : 0.4,
        cursor: enabled ? 'pointer' : 'default',
    });

    const canUndo = editor.can().undo();
    const canRedo = editor.can().redo();

    return (
        <div className="rte">
            <div className="rte-toolbars">
                <div className="rte-toolbar">
                    <button type="button" title="Отменить (Ctrl+Z)" disabled={!canUndo} style={stepBtn(canUndo)}
                        onClick={() => editor.chain().focus().undo().run()}>↶</button>
                    <button type="button" title="Повторить (Ctrl+Y / Ctrl+Shift+Z)" disabled={!canRedo} style={stepBtn(canRedo)}
                        onClick={() => editor.chain().focus().redo().run()}>↷</button>
                    <span className="rte-sep" />
                    <button type="button" title="Жирный" style={btn(editor.isActive('bold'))}
                        onClick={() => editor.chain().focus().toggleBold().run()}><b>B</b></button>
                    <button type="button" title="Курсив" style={btn(editor.isActive('italic'))}
                        onClick={() => editor.chain().focus().toggleItalic().run()}><i>I</i></button>
                    <span className="rte-sep" />
                    {headingLevels.map(level => (
                        <button key={level} type="button" title={HEADING_TITLES[level] || `Заголовок ${level}`}
                            style={btn(editor.isActive('heading', { level }))}
                            onClick={() => editor.chain().focus().toggleHeading({ level }).run()}>H{level}</button>
                    ))}
                    <span className="rte-sep" />
                    {ALIGN_BUTTONS.map(({ align: value, title }) => (
                        <button key={value} type="button" title={title} aria-label={title}
                            aria-pressed={align === value} style={btn(align === value)}
                            onClick={() => setAlign(value)}><AlignIcon align={value} /></button>
                    ))}
                    <span className="rte-sep" />
                    <button type="button" title="Маркированный список" style={btn(editor.isActive('bulletList'))}
                        onClick={() => editor.chain().focus().toggleBulletList().run()}>• Список</button>
                    <button type="button" title="Нумерованный список" style={btn(editor.isActive('orderedList'))}
                        onClick={() => editor.chain().focus().toggleOrderedList().run()}>1. Список</button>
                    <span className="rte-sep" />
                    <button type="button" title="Код (строка)" style={btn(editor.isActive('code'))}
                        onClick={() => editor.chain().focus().toggleCode().run()}>{'< >'}</button>
                    <button type="button" title="Блок кода" style={btn(editor.isActive('codeBlock'))}
                        onClick={() => editor.chain().focus().toggleCodeBlock().run()}>Код-блок</button>
                    <button type="button" title="Цитата" style={btn(editor.isActive('blockquote'))}
                        onClick={() => editor.chain().focus().toggleBlockquote().run()}>❝</button>
                    <span className="rte-sep" />
                    <button type="button" title="Вставить изображение (или просто вставьте/перетащите картинку)"
                        style={btn(false)} onClick={() => fileInputRef.current?.click()}>🖼 Картинка</button>
                    <button type="button" title="Вставить таблицу" style={btn(inTable)}
                        onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}>▦ Таблица</button>
                    <button type="button" title="Вставить формулу (LaTeX)" style={btn(false)}
                        onClick={() => openFormula({})}>∑ Формула</button>
                </div>
                {inTable && (
                    <div className="rte-toolbar rte-toolbar--table">
                        <span className="rte-toolbar__label">Таблица:</span>
                        <button type="button" title="Добавить строку ниже" style={btn(false)}
                            onClick={() => editor.chain().focus().addRowAfter().run()}>+ Строка</button>
                        <button type="button" title="Добавить столбец справа" style={btn(false)}
                            onClick={() => editor.chain().focus().addColumnAfter().run()}>+ Столбец</button>
                        <button type="button" title="Удалить строку" style={btn(false)}
                            onClick={() => editor.chain().focus().deleteRow().run()}>− Строка</button>
                        <button type="button" title="Удалить столбец" style={btn(false)}
                            onClick={() => editor.chain().focus().deleteColumn().run()}>− Столбец</button>
                        <span className="rte-sep" />
                        <button type="button" title="Первая строка — заголовок таблицы" style={btn(false)}
                            onClick={() => editor.chain().focus().toggleHeaderRow().run()}>Строка заголовка</button>
                        <button type="button" title="Объединить выделенные ячейки или разделить объединённую" style={btn(false)}
                            onClick={() => editor.chain().focus().mergeOrSplit().run()}>Объединить / разделить</button>
                        <span className="rte-sep" />
                        <button type="button" title="Удалить таблицу" style={btn(false)}
                            onClick={() => editor.chain().focus().deleteTable().run()}>Удалить таблицу</button>
                    </div>
                )}
                {imageSelected && (
                    <div className="rte-toolbar rte-toolbar--image">
                        <span className="rte-toolbar__label">Картинка:</span>
                        <button type="button" title="Уменьшить картинку" style={btn(false)}
                            onClick={() => resizeSelectedImage(0.8)}>− Меньше</button>
                        <button type="button" title="Увеличить картинку" style={btn(false)}
                            onClick={() => resizeSelectedImage(1.25)}>+ Больше</button>
                        <button type="button" title="Вернуть исходный размер картинки" style={btn(false)}
                            onClick={() => resizeSelectedImage(null)}>Исходный размер</button>
                        <span className="rte-toolbar__hint">или потяните за уголок картинки</span>
                    </div>
                )}
            </div>
            <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                style={{ display: 'none' }}
                onChange={handleFilePick}
            />
            <EditorContent editor={editor} className="rte-content" data-placeholder={placeholder} />
            {formula && (
                <FormulaDialog initial={formula} onSubmit={submitFormula} onDelete={deleteFormula} onClose={closeFormula} />
            )}
        </div>
    );
}

export default RichTextEditor;
