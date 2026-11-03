export function shuffledItems(items, random = Math.random) {
    const result = [...items];
    for (let i = result.length - 1; i > 0; i--) {
        const j = Math.floor(random() * (i + 1));
        [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
}

// Position is one-based, as in the shared drag-and-drop controls.
export function moveItem(items, id, position) {
    const from = items.findIndex(item => item.id === id);
    if (from < 0 || position < 1 || position > items.length) return items;
    const result = [...items];
    const [item] = result.splice(from, 1);
    result.splice(position - 1, 0, item);
    return result;
}
