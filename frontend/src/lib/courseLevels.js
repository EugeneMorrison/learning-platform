// Course difficulty (Course.level in api/models.py), in difficulty order.
// No level is stored as null and shown as «Не указан» (the select's '' value).
export const COURSE_LEVELS = [
    { value: 'BEGINNER', label: 'Начальный' },
    { value: 'INTERMEDIATE', label: 'Средний' },
    { value: 'ADVANCED', label: 'Продвинутый' },
];

export const NO_LEVEL_LABEL = 'Не указан';
