import { createContext, useContext } from 'react';

/**
 * The lesson page's part of the app header: the lessons button, the breadcrumb
 * and "Решено X из Y задач". AppHeader sits above the routes (App.jsx), so
 * LessonViewer can't pass it props; it publishes the data here instead and
 * clears it on unmount.
 *
 * Value: null, or { courseId, courseTitle, lessonTitle, taskIds, solvedIds,
 * nextStep, lessonsOpen, onOpenLessons, onTitleClick }.
 * solvedIds is LessonViewer's own Set of solved block ids (the one source of
 * truth); the header counts X from it, so a new Set there updates the header.
 * nextStep is where the lesson leads (LessonViewer's nextStep()), shown once
 * every task is solved. The lessons panel stays LessonViewer's: the header's
 * button opens it (onOpenLessons) and takes focus back when lessonsOpen turns
 * false.
 *
 * Two contexts: the page only needs the setter, which never changes, so
 * publishing doesn't re-render the page.
 */
export const LessonBarContext = createContext(null);
export const SetLessonBarContext = createContext(() => {});

export function useLessonBar() {
    return useContext(LessonBarContext);
}

export function useSetLessonBar() {
    return useContext(SetLessonBarContext);
}
