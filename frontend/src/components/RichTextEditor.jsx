import { useEffect } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import './RichTextEditor.css';

/**
 * WYSIWYG editor for TEXT block / CODE prompt HTML.
 *
 * The teacher edits visually (no HTML knowledge needed); we persist the
 * generated HTML via onChange. TipTap's codeBlock renders as <pre><code>,
 * which TextBlock already syntax-highlights with highlight.js.
 */
function RichTextEditor({ value, onChange, placeholder }) {
    const editor = useEditor({
        extensions: [StarterKit],
        content: value || '',
        // Avoid SSR hydration warnings; harmless on the client.
        immediatelyRender: false,
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

    return (
        <div className="rte">
            <div className="rte-toolbar">
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
            </div>
            <EditorContent editor={editor} className="rte-content" data-placeholder={placeholder} />
        </div>
    );
}

export default RichTextEditor;
