import { htmlNodes } from '../lib/sortHtml';

export default function SortItem({ text, html = false }) {
    return <div className="sort-item__text">{html
        ? htmlNodes(new DOMParser().parseFromString(text, 'text/html').body.childNodes)
        : text}</div>;
}
