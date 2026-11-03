"""Sorting answers use opaque item IDs, never positions in the solution."""

import uuid

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ParseError


def content_error(content):
    if not isinstance(content.get('prompt'), str) or not content['prompt'].strip():
        return "SORT requires a prompt describing the required order"
    if 'html' in content and type(content['html']) is not bool:
        return "SORT 'html' must be true or false"
    for field in ('feedback_correct', 'feedback_incorrect'):
        if field in content and not isinstance(content[field], str):
            return f"SORT '{field}' must be a string"
    items = content.get('items')
    if not isinstance(items, list) or len(items) < 2:
        return "SORT requires at least two items"
    ids = []
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get('text'), str)
                or not item['text'].strip()):
            return "SORT items must contain non-empty text"
        try:
            item_id = item.get('id')
            parsed = uuid.UUID(item_id) if isinstance(item_id, str) else None
            if parsed is None or parsed.version != 4 or str(parsed) != item_id:
                return "SORT item IDs must be canonical random UUIDs (version 4)"
        except ValueError:
            return "SORT item IDs must be canonical random UUIDs (version 4)"
        ids.append(item_id)
    if len(set(ids)) != len(ids):
        return "SORT item IDs must be unique"
    return None


def prepare_answer(block, raw):
    if not isinstance(raw, dict):
        raise ParseError('Передайте порядок всех элементов.')
    order = raw.get('order')
    items = block.content['items']
    correct = [item['id'] for item in items]
    if (not isinstance(order, list) or len(order) != len(correct)
            or any(not isinstance(item_id, str) for item_id in order)
            or len(set(order)) != len(order) or set(order) != set(correct)):
        raise ParseError('Расположите все элементы без повторов.')
    if 'sort_revision' in raw:
        revision = raw['sort_revision']
        try:
            when = parse_datetime(revision) if isinstance(revision, str) else None
        except ValueError:
            when = None
        if when != block.updated_at:
            raise ParseError('Задание изменилось. Обновите страницу перед отправкой.')
    by_id = {item['id']: item for item in items}
    # Keep the submitted item text for history even after author edits. Only
    # copy server-owned fields; client snapshots/verdicts are ignored.
    answer = {'order': order, 'items': [{'id': key, 'text': by_id[key]['text']} for key in order],
              'html': block.content.get('html', False)}
    # Identical entries (e.g. repeated lines of code) are interchangeable.
    return answer, [by_id[key]['text'] for key in order] == [item['text'] for item in items]
