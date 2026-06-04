import { EditorView, ViewPlugin, Decoration } from '@codemirror/view';
import { HighlightStyle, syntaxHighlighting, syntaxTree } from '@codemirror/language';
import { RangeSetBuilder } from '@codemirror/state';
import { tags as t } from '@lezer/highlight';

const BG = '#2B2B2B';
const GUTTER_BG = '#313335';
const FG = '#F0F0F0';
const CURSOR = '#FFFFFF';
const SELECTION = '#2D5396';
const LINE_NUMBER = '#787878';
const ACTIVE_LINE = '#323232';
const ACTIVE_LINE_NUMBER = '#D8D8D8';

const KEYWORD = '#FF9559';
const STRING = '#A5C261';
const NUMBER = '#7FB3D7';
const COMMENT = '#9E9E9E';
const FUNCTION_DEF = '#FFD580';
const DECORATOR = '#D7D139';
const BUILTIN = '#B5B5E0';
const ESCAPE = '#FF9559';
const DOCSTRING = '#8AB76A';

const darculaTheme = EditorView.theme(
    {
        '&': {
            color: FG,
            backgroundColor: BG,
        },
        '.cm-scroller': {
            backgroundColor: BG,
            fontFamily: "'JetBrains Mono', Consolas, monospace",
            lineHeight: '1.6',
        },
        '.cm-content': {
            color: FG,
            caretColor: CURSOR,
            fontFamily: "'JetBrains Mono', Consolas, monospace",
            fontSize: '14px',
            padding: '8px 0',
        },
        '.cm-cursor, .cm-dropCursor': {
            borderLeftColor: CURSOR,
            borderLeftWidth: '2px',
        },
        '.cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-content ::selection': {
            background: SELECTION + ' !important',
        },
        '.cm-selectionMatch': {
            backgroundColor: '#3A5675',
        },
        '.cm-activeLine': {
            backgroundColor: 'transparent',
        },
        '.cm-gutters': {
            backgroundColor: GUTTER_BG,
            color: LINE_NUMBER,
            border: 'none',
            fontFamily: "'JetBrains Mono', Consolas, monospace",
        },
        '.cm-activeLineGutter': {
            backgroundColor: GUTTER_BG,
            color: ACTIVE_LINE_NUMBER,
        },
        '.cm-lineNumbers .cm-gutterElement': {
            padding: '0 12px 0 10px',
            minWidth: '24px',
        },
        '.cm-matchingBracket, .cm-nonmatchingBracket': {
            backgroundColor: '#3B514D',
            outline: '1px solid #43574F',
        },
        '.cm-py-builtin, .cm-py-builtin span': {
            color: BUILTIN + ' !important',
        },
    },
    { dark: true }
);

const PYTHON_BUILTINS = new Set([
    'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'bytearray', 'bytes', 'callable',
    'chr', 'classmethod', 'compile', 'complex', 'delattr', 'dict', 'dir', 'divmod',
    'enumerate', 'eval', 'exec', 'filter', 'float', 'format', 'frozenset', 'getattr',
    'globals', 'hasattr', 'hash', 'help', 'hex', 'id', 'input', 'int', 'isinstance',
    'issubclass', 'iter', 'len', 'list', 'locals', 'map', 'max', 'memoryview', 'min',
    'next', 'object', 'oct', 'open', 'ord', 'pow', 'print', 'property', 'range',
    'repr', 'reversed', 'round', 'set', 'setattr', 'slice', 'sorted', 'staticmethod',
    'str', 'sum', 'super', 'tuple', 'type', 'vars', 'zip',
]);

const builtinMark = Decoration.mark({ class: 'cm-py-builtin' });

function buildBuiltinDecorations(view) {
    const builder = new RangeSetBuilder();
    for (const { from, to } of view.visibleRanges) {
        syntaxTree(view.state).iterate({
            from, to,
            enter: (node) => {
                if (node.name === 'VariableName') {
                    const text = view.state.doc.sliceString(node.from, node.to);
                    if (PYTHON_BUILTINS.has(text)) {
                        builder.add(node.from, node.to, builtinMark);
                    }
                }
            },
        });
    }
    return builder.finish();
}

const pythonBuiltinsPlugin = ViewPlugin.fromClass(
    class {
        constructor(view) {
            this.decorations = buildBuiltinDecorations(view);
        }
        update(update) {
            if (update.docChanged || update.viewportChanged) {
                this.decorations = buildBuiltinDecorations(update.view);
            }
        }
    },
    { decorations: (v) => v.decorations }
);

const darculaHighlight = HighlightStyle.define([
    { tag: t.keyword, color: KEYWORD },
    { tag: t.controlKeyword, color: KEYWORD },
    { tag: t.moduleKeyword, color: KEYWORD },
    { tag: t.operatorKeyword, color: KEYWORD },
    { tag: t.definitionKeyword, color: KEYWORD },
    { tag: t.bool, color: KEYWORD },
    { tag: t.null, color: KEYWORD },
    { tag: t.self, color: KEYWORD, fontStyle: 'italic' },

    { tag: t.string, color: STRING },
    { tag: t.special(t.string), color: STRING },
    { tag: t.docString, color: DOCSTRING, fontStyle: 'italic' },
    { tag: t.escape, color: ESCAPE },
    { tag: t.regexp, color: STRING },

    { tag: t.number, color: NUMBER },
    { tag: t.integer, color: NUMBER },
    { tag: t.float, color: NUMBER },

    { tag: t.comment, color: COMMENT, fontStyle: 'italic' },
    { tag: t.lineComment, color: COMMENT, fontStyle: 'italic' },
    { tag: t.blockComment, color: COMMENT, fontStyle: 'italic' },

    { tag: t.function(t.definition(t.variableName)), color: FUNCTION_DEF },
    { tag: t.definition(t.function(t.variableName)), color: FUNCTION_DEF },
    { tag: t.function(t.variableName), color: FG },
    { tag: t.standard(t.variableName), color: BUILTIN },
    { tag: t.variableName, color: FG },
    { tag: t.propertyName, color: FG },
    { tag: t.className, color: FG },
    { tag: t.typeName, color: FG },

    { tag: t.meta, color: DECORATOR },
    { tag: t.annotation, color: DECORATOR },

    { tag: t.operator, color: FG },
    { tag: t.punctuation, color: FG },
    { tag: t.bracket, color: FG },
    { tag: t.paren, color: FG },
    { tag: t.brace, color: FG },

    { tag: t.invalid, color: '#FF5370' },
]);

export const pycharmDarcula = [darculaTheme, syntaxHighlighting(darculaHighlight), pythonBuiltinsPlugin];
