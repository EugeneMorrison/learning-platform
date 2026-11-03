"""Table selections, private answer keys and trusted display snapshots."""

import uuid

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ParseError


def content_error(content):
    if not isinstance(content.get('prompt'), str) or not content['prompt'].strip():
        return "TABLE requires a prompt"
    for field in ('multiple_answers', 'shuffle_rows', 'shuffle_columns', 'any_answer_correct'):
        if field in content and type(content[field]) is not bool:
            return f"TABLE '{field}' must be true or false"
    for field in ('feedback_correct', 'feedback_incorrect'):
        if field in content and not isinstance(content[field], str):
            return f"TABLE '{field}' must be a string"
    ids = []
    for field in ('rows', 'columns'):
        items = content.get(field)
        if not isinstance(items, list) or not items:
            return f"TABLE requires at least one item in '{field}'"
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip():
                return f"TABLE '{field}' must contain non-empty text"
            key = item.get('id')
            try:
                parsed = uuid.UUID(key) if isinstance(key, str) else None
            except ValueError:
                parsed = None
            if parsed is None or parsed.version != 4 or str(parsed) != key:
                return "TABLE item IDs must be canonical random UUIDs (version 4)"
            ids.append(key)
    if len(set(ids)) != len(ids):
        return "TABLE item IDs must be unique across rows and columns"
    correct = content.get('correct_cells', {})
    row_ids = {item['id'] for item in content['rows']}
    column_ids = {item['id'] for item in content['columns']}
    if not isinstance(correct, dict) or set(correct) - row_ids:
        return "TABLE 'correct_cells' must be keyed by valid row IDs"
    if not content.get('any_answer_correct') and set(correct) != row_ids:
        return "TABLE requires a correct selection for every row"
    for selected in correct.values():
        if (not isinstance(selected, list) or any(not isinstance(key, str) for key in selected)
                or len(set(selected)) != len(selected) or set(selected) - column_ids):
            return "TABLE correct cells must contain unique valid column IDs"
        if not content.get('multiple_answers') and (
                len(selected) > 1 or (not content.get('any_answer_correct') and len(selected) != 1)):
            return "Single-choice TABLE requires exactly one correct cell per row"
    return None


def student_content(content):
    public = {key: content[key] for key in ('prompt', 'multiple_answers', 'shuffle_rows',
                                          'shuffle_columns', 'any_answer_correct') if key in content}
    for field in ('rows', 'columns'):
        public[field] = [{'id': item['id'], 'text': item['text']} for item in content.get(field, [])]
    return public


def prepare_answer(block, raw):
    if not isinstance(raw, dict):
        raise ParseError('Передайте выбранные ячейки таблицы.')
    content = block.content
    public = student_content(content)
    ids = {field: [item['id'] for item in public[field]] for field in ('rows', 'columns')}
    selected = raw.get('selected')
    if not isinstance(selected, dict) or set(selected) != set(ids['rows']):
        raise ParseError('Передайте ответ для каждой строки таблицы.')
    for cells in selected.values():
        if (not isinstance(cells, list) or any(not isinstance(key, str) for key in cells)
                or len(set(cells)) != len(cells) or set(cells) - set(ids['columns'])):
            raise ParseError('Выберите допустимые ячейки без повторов.')
        if not content.get('multiple_answers') and len(cells) != 1:
            raise ParseError('Выберите один вариант в каждой строке.')
    orders = {}
    for field, order_field, shuffle_field in (
            ('rows', 'row_order', 'shuffle_rows'), ('columns', 'column_order', 'shuffle_columns')):
        order = raw.get(order_field, ids[field])
        if (not isinstance(order, list) or any(not isinstance(key, str) for key in order)
                or len(order) != len(ids[field]) or set(order) != set(ids[field])):
            raise ParseError('Недопустимый порядок строк или столбцов.')
        if not content.get(shuffle_field) and order != ids[field]:
            raise ParseError('Порядок строк или столбцов должен оставаться неизменным.')
        orders[field] = order
    if 'table_revision' in raw:
        revision = raw['table_revision']
        try:
            when = parse_datetime(revision) if isinstance(revision, str) else None
        except ValueError:
            when = None
        if when != block.updated_at:
            raise ParseError('Задание изменилось. Обновите страницу перед отправкой.')
    snapshot = {'prompt': public['prompt'], 'multiple_answers': bool(content.get('multiple_answers')),
                'any_answer_correct': bool(content.get('any_answer_correct')),
                'revision': block.updated_at.isoformat()}
    for field in ('rows', 'columns'):
        by_id = {item['id']: item for item in public[field]}
        snapshot[field] = [by_id[key] for key in orders[field]]
    answer = {'selected': {key: list(cells) for key, cells in selected.items()}, 'table_snapshot': snapshot}
    correct = bool(content.get('any_answer_correct')) or all(
        set(selected[key]) == set(content['correct_cells'][key]) for key in ids['rows'])
    return answer, correct
