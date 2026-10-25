import katex from 'katex';
import 'katex/dist/katex.min.css';

/**
 * LaTeX formulas in author HTML (the lesson editor's «∑ Формула», Tiptap's
 * mathematics extension) are stored empty, the formula in data-latex:
 *   <span data-type="inline-math" data-latex="…"></span>  — inside a line
 *   <div data-type="block-math" data-latex="…"></div>      — on a line of its own
 * A formula on a line of its own is centred, or at the left with
 * data-align="left" (kept on the element; see blocks.css). renderMath fills them with KaTeX's HTML for display. A broken formula shows
 * KaTeX's error in red instead of breaking the block. Display only: the
 * stored HTML is not changed.
 */
const cache = new Map();
const CACHE_LIMIT = 500;

export function formulaHtml(latex, displayMode) {
    const key = `${displayMode ? 'B' : 'I'}${latex}`;
    let html = cache.get(key);
    if (html === undefined) {
        html = katex.renderToString(latex, { displayMode, throwOnError: false });
        if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value);
        cache.set(key, html);
    }
    return html;
}

export function renderMath(html) {
    if (!html || !html.includes('data-latex')) return html || '';
    const template = document.createElement('template');
    template.innerHTML = html;
    const formulas = template.content.querySelectorAll('[data-type="inline-math"], [data-type="block-math"]');
    for (const el of formulas) {
        el.innerHTML = formulaHtml(el.getAttribute('data-latex') || '', el.dataset.type === 'block-math');
    }
    return template.innerHTML;
}
