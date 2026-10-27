import './LessonProgress.css';

/**
 * "Решено X из Y задач", the percentage and a progress bar for one lesson.
 * X is counted from solvedIds (a Set of block ids), Y is taskIds.length; a
 * lesson without tasks shows nothing. Used in the app header and, in an
 * embedded lesson (no app header), on the page itself.
 *
 * All solved: "Решено N из N задач ✅", a green bar, and at the right end
 * completeAction (the app header's next-lesson link) or "✓ Урок пройден".
 */
function LessonProgress({ taskIds, solvedIds, completeAction }) {
    const solved = taskIds.filter(id => solvedIds.has(id)).length;
    return <TaskProgress solved={solved} total={taskIds.length} completeAction={completeAction} />;
}

/**
 * The same bar from plain counts (the course page sums its lessons).
 * completeText replaces "✓ Урок пройден" when all are solved. label replaces
 * "Решено X из Y задач" (the author's view of all students: the counts are
 * then summed over students, so the bar reports a percentage, labelled ariaLabel).
 */
export function TaskProgress({
    solved, total, completeAction, completeText = '✓ Урок пройден', label, ariaLabel = 'Решено задач',
}) {
    if (total === 0) return null;
    const percent = Math.round((solved / total) * 100);
    const complete = solved === total;

    return (
        <div className={complete ? 'lesson-progress lesson-progress--complete' : 'lesson-progress'}>
            <div className="lesson-progress__labels">
                <span className="lesson-progress__count">
                    {label || <><span className="lesson-progress__verb">Решено </span>{solved} из {total} задач</>}
                </span>
                {complete && <span className="lesson-progress__emoji" aria-hidden="true">✅</span>}
                <span className="lesson-progress__percent">
                    {complete ? (completeAction || completeText) : `${percent}%`}
                </span>
            </div>
            <div
                className="lesson-progress__track"
                role="progressbar"
                aria-label={ariaLabel}
                aria-valuemin={0}
                aria-valuemax={label ? 100 : total}
                aria-valuenow={label ? percent : solved}
            >
                {/* Width is data, so it stays inline. */}
                <div className="lesson-progress__fill" style={{ width: `${percent}%` }} />
            </div>
        </div>
    );
}

export default LessonProgress;
