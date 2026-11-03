import SortItem from './SortItem';
import './sorting.css';
import './matching.css';

export function MatchItem({ item, html = false }) {
    return item.text.trim()
        ? <SortItem text={item.text} html={html} />
        : <span className="match-empty">Без пары</span>;
}

// Submitted pairs are server-owned snapshots, so history survives author edits.
export default function MatchPairs({ rows, html = false }) {
    return <ol className="match-list" aria-label="Сопоставленные элементы">
        {rows.map(row => <li key={row.left.id} className="match-row">
            <div className="match-cell match-cell--left"><MatchItem item={row.left} html={html} /></div>
            <div className="match-cell"><MatchItem item={row.right} html={html} /></div>
        </li>)}
    </ol>;
}
