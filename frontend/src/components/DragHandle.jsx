function DragHandle(props) {
    return (
        <button type="button" className="btn btn-secondary btn-sm reorder-handle"
            aria-label="Перетащить для изменения порядка" title="Перетащите, чтобы изменить порядок. Также можно использовать стрелки."
            {...props}>
            <span aria-hidden="true">⠿</span>
        </button>
    );
}

export default DragHandle;
