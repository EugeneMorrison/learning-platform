import { useEffect, useRef } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import api from '../api';
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
 */
function RichTextEditor({ value, onChange, placeholder }) {
    const fileInputRef = useRef(null);

    const editor = useEditor({
        extensions: [
            StarterKit,
            Image.configure({ inline: false, allowBase64: false }),
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
        border: '1px solid #cbd5e1',
        borderRadius: '6px',
        background: active ? '#0C4B33' : 'white',
        color: active ? 'white' : '#334155',
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
                <button type="button" title="Заголовок" style={btn(editor.isActive('heading', { level: 2 }))}
                    onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}>H2</button>
                <button type="button" title="Подзаголовок" style={btn(editor.isActive('heading', { level: 3 }))}
                    onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}>H3</button>
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
            </div>
            <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp,image/svg+xml"
                style={{ display: 'none' }}
                onChange={handleFilePick}
            />
            <EditorContent editor={editor} className="rte-content" data-placeholder={placeholder} />
        </div>
    );
}

export default RichTextEditor;
