"""Matching tasks store answer pairs privately and expose independent lists."""

from collections import Counter
import uuid

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ParseError


def content_error(content):
    if not isinstance(content.get('prompt'), str) or not content['prompt'].strip():
        return "MATCH requires a prompt describing what to match"
    for field in ('html', 'keep_left_order'):
        if field in content and type(content[field]) is not bool:
            return f"MATCH '{field}' must be true or false"
    for field in ('feedback_correct', 'feedback_incorrect'):
        if field in content and not isinstance(content[field], str):
            return f"MATCH '{field}' must be a string"
    pairs = content.get('pairs')
    if not isinstance(pairs, list) or len(pairs) < 2:
        return "MATCH requires at least two rows"
    ids = []
    texts = {'left': [], 'right': []}
    for pair in pairs:
        if not isinstance(pair, dict):
            return "MATCH rows must contain left and right items"
        for side in ('left', 'right'):
            item = pair.get(side)
            if not isinstance(item, dict) or not isinstance(item.get('text'), str):
                return "MATCH items must contain text (empty for an unmatched item)"
            texts[side].append(item['text'])
            item_id = item.get('id')
            try:
                parsed = uuid.UUID(item_id) if isinstance(item_id, str) else None
            except ValueError:
                parsed = None
            if parsed is None or parsed.version != 4 or str(parsed) != item_id:
                return "MATCH item IDs must be canonical random UUIDs (version 4)"
            ids.append(item_id)
        if not pair['left']['text'].strip() and not pair['right']['text'].strip():
            return "MATCH rows cannot be empty on both sides"
    if len(set(ids)) != len(ids):
        return "MATCH item IDs must be unique across both columns"
    if any(not any(text.strip() for text in column) for column in texts.values()):
        return "MATCH requires at least one non-empty item in each column"
    return None


def student_content(content):
    public = {key: content[key] for key in ('prompt', 'html', 'keep_left_order') if key in content}
    for side in ('left', 'right'):
        items = [{'id': pair[side]['id'], 'text': pair[side]['text']} for pair in content.get('pairs', [])]
        # Preserve only the explicitly requested left order. Neither list's
        # order nor IDs reveal which entries belong together.
        public[side] = items if side == 'left' and content.get('keep_left_order') else sorted(items, key=lambda item: item['id'])
    return public


def prepare_answer(block, raw):
    if not isinstance(raw, dict):
        raise ParseError('Передайте сопоставление всех элементов.')
    pairs = block.content['pairs']
    columns = {side: {pair[side]['id']: pair[side]['text'] for pair in pairs} for side in ('left', 'right')}
    orders = {}
    for side in ('left', 'right'):
        order = raw.get(f'{side}_order')
        if (not isinstance(order, list) or len(order) != len(pairs)
                or any(not isinstance(item_id, str) for item_id in order)
                or len(set(order)) != len(order) or set(order) != set(columns[side])):
            raise ParseError('Используйте все элементы каждого столбца ровно один раз.')
        orders[side] = order
    if block.content.get('keep_left_order') and orders['left'] != [pair['left']['id'] for pair in pairs]:
        raise ParseError('Порядок первого столбца должен оставаться неизменным.')
    if 'match_revision' in raw:
        revision = raw['match_revision']
        try:
            when = parse_datetime(revision) if isinstance(revision, str) else None
        except ValueError:
            when = None
        if when != block.updated_at:
            raise ParseError('Задание изменилось. Обновите страницу перед отправкой.')
    rows = [{side: {'id': orders[side][index], 'text': columns[side][orders[side][index]]}
             for side in ('left', 'right')} for index in range(len(pairs))]
    # Empty placeholders and repeated labels are indistinguishable to students.
    # Compare pair multisets so their IDs and row ordering do not affect grading.
    def pair_values(row):
        return tuple(row[side]['text'] if row[side]['text'].strip() else '' for side in ('left', 'right'))
    is_correct = Counter(map(pair_values, rows)) == Counter(map(pair_values, pairs))
    answer = {'left_order': orders['left'], 'right_order': orders['right'],
              'rows': rows, 'html': block.content.get('html', False)}
    return answer, is_correct
