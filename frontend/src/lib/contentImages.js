/**
 * Wrap every <img> in author HTML in a <span class="content-figure">, a box that
 * scrolls sideways when the picture is wider than the column. Lesson formulas
 * are pasted as images; on phones they keep their natural size (readable) and
 * scroll inside the box instead of shrinking (see .content-figure in
 * components/blocks.css). Display only: the stored HTML is not changed.
 */
export function wrapImages(html) {
    return (html || '').replace(/<img\b[^>]*>/gi, img => `<span class="content-figure">${img}</span>`);
}

/**
 * Wrap every <table> in author HTML in a .content-figure box too (block-level:
 * content-figure--table), so a table wider than the column scrolls sideways
 * instead of stretching the page, with the same fade at the right edge. Open
 * and close tags are replaced separately, so a table inside a cell still nests.
 * Display only: the stored HTML is not changed.
 */
export function wrapTables(html) {
    return (html || '')
        .replace(/<table\b/gi, '<div class="content-figure content-figure--table"><table')
        .replace(/<\/table>/gi, '</table></div>');
}

/**
 * Mark .content-figure boxes under `root` that have more picture to the right
 * (class content-figure--more → a soft fade at the right edge, see blocks.css).
 * Re-checked when a picture loads or the column resizes (ResizeObserver) and
 * while the box is scrolled, so the fade goes away at the end. Returns cleanup.
 */
export function watchFigureOverflow(root) {
    if (!root || typeof ResizeObserver === 'undefined') return undefined;
    const figures = [...root.querySelectorAll('.content-figure')];
    const update = el => el.classList.toggle(
        'content-figure--more', el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
    const onScroll = e => update(e.currentTarget);
    const observer = new ResizeObserver(entries => {
        for (const entry of entries) update(entry.target.closest('.content-figure'));
    });
    for (const fig of figures) {
        observer.observe(fig);
        const img = fig.querySelector('img');
        if (img) observer.observe(img); // its size changes when it finishes loading
        fig.addEventListener('scroll', onScroll, { passive: true });
        update(fig);
    }
    return () => {
        observer.disconnect();
        for (const fig of figures) fig.removeEventListener('scroll', onScroll);
    };
}
