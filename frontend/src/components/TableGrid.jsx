import { useId } from 'react';
import './tableTask.css';

export default function TableGrid({ rows, columns, selected = {}, multiple = false,
    namePrefix, disabled = false, onChange, label = 'Таблица ответов' }) {
    const instance = useId();
    return <div className="table-task__scroll" role="region" aria-label={label} tabIndex={0}>
        <table className="table-task__grid">
            <thead><tr><th scope="col">Ряды:</th>{columns.map(column =>
                <th key={column.id} scope="col">{column.text}</th>)}</tr></thead>
            <tbody>{rows.map(row => <tr key={row.id}>
                <th scope="row">{row.text}</th>
                {columns.map(column => <td key={column.id}>
                    <input type={multiple ? 'checkbox' : 'radio'} name={`${namePrefix}-${instance}-${row.id}`}
                        aria-label={`${row.text} — ${column.text}`} checked={(selected[row.id] || []).includes(column.id)}
                        disabled={disabled || !onChange}
                        onChange={event => onChange?.(row.id, column.id, event.target.checked)} />
                </td>)}
            </tr>)}</tbody>
        </table>
    </div>;
}
