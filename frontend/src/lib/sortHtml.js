import { createElement } from 'react';

const ALLOWED = new Set(['br', 'b', 'i', 'strong', 'em', 'strike', 'h1', 'h2', 'h3',
    'ol', 'li', 'ul', 'blockquote', 'code', 'abbr']);
const DROP = new Set(['script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template']);

// Build React nodes from an inert document. Only the documented tags and
// abbr's title attribute survive; event handlers, URLs and styles never do.
export function htmlNodes(nodes) {
    return Array.from(nodes).map((node, index) => {
        if (node.nodeType === 3) return node.textContent;
        if (node.nodeType !== 1) return null;
        const tag = node.tagName.toLowerCase();
        if (DROP.has(tag)) return null;
        const children = htmlNodes(node.childNodes);
        if (!ALLOWED.has(tag)) return children;
        const props = { key: index };
        if (tag === 'abbr' && node.hasAttribute('title')) props.title = node.getAttribute('title');
        return tag === 'br' ? createElement(tag, props) : createElement(tag, props, children);
    });
}
