import './LessonProgress.css';

/**
 * "Решено X из Y задач", the percentage and a progress bar for one lesson.
 * X is counted from solvedIds (a Set of block ids), Y is taskIds.length; a
 * lesson without tasks shows nothing. Used in the app header and, in an
 * embedded lesson (no app header), on the page itself.
 */
function LessonProgress({ taskIds, solvedIds }) {
    const total = taskIds.length;
    if (total === 0) return null;
    const solved = taskIds.filter(id => solvedIds.has(id)).length;
    const percent = Math.round((solved / total) * 100);
    const complete = solved === total;

    return (
        <div className={complete ? 'lesson-progress lesson-progress--complete' : 'lesson-progress'}>
            <div className="lesson-progress__labels">
                <span className="lesson-progress__count">
                    <span className="lesson-progress__verb">Решено </span>{solved} из {total} задач
                </span>
                <span className="lesson-progress__percent">{complete ? '✓ Урок пройден' : `${percent}%`}</span>
            </div>
            <div
                className="lesson-progress__track"
                role="progressbar"
                aria-label="Решено задач"
                aria-valuemin={0}
                aria-valuemax={total}
                aria-valuenow={solved}
            >
                {/* Width is data, so it stays inline. */}
                <div className="lesson-progress__fill" style={{ width: `${percent}%` }} />
            </div>
        </div>
    );
}

export default LessonProgress;
