// A null draft selects free access. A string holds the author's paid price,
// including an empty input while they are entering the amount.
export default function CoursePriceFields({ value, onChange, disabled = false }) {
    return (
        <>
            <label className="course-price-field">
                <span>Доступ к курсу</span>
                <select className="input" value={value === null ? 'free' : 'paid'}
                    disabled={disabled} onChange={event => onChange(event.target.value === 'paid' ? '' : null)}>
                    <option value="free">Бесплатный</option>
                    <option value="paid">Платный</option>
                </select>
            </label>
            {value !== null && (
                <label className="course-price-field">
                    <span>Цена, ₽</span>
                    <input className="input" type="number" min="0.01" max="99999999.99" step="0.01"
                        required disabled={disabled} value={value} onChange={event => onChange(event.target.value)} />
                </label>
            )}
        </>
    );
}
