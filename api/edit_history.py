"""Owner-only history of successful editor API mutations, in the same transaction.
No guessed history is backfilled for changes made before this feature.
"""
import copy
import uuid

from django.db import transaction
from django.utils.html import strip_tags
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .models import Block, Course, CourseEdit, Lesson


def lesson_number(lesson):
    ids = list(Lesson.objects.filter(course_id=lesson.course_id).order_by('order_index', 'id').values_list('pk', flat=True))
    return ids.index(lesson.pk) + 1


def snapshot(obj):
    data = {'id': str(obj.pk)}
    if isinstance(obj, Course):
        data.update(title=obj.title, description=obj.description, level=obj.level,
                    is_published=obj.is_published, price=str(obj.price), cover=obj.cover.name or '')
    elif isinstance(obj, Lesson):
        data.update(title=obj.title, course_id=str(obj.course_id), order_index=obj.order_index,
                    lesson_number=lesson_number(obj))
    else:
        ids = list(Block.objects.filter(lesson_id=obj.lesson_id, type=obj.type)
                   .order_by('order_index', 'id').values_list('pk', flat=True))
        data.update(lesson_id=str(obj.lesson_id), type=obj.type, order_index=obj.order_index,
                    content=copy.deepcopy(obj.content), lesson_number=lesson_number(obj.lesson),
                    block_number=ids.index(obj.pk) + 1)
    return data


def ordered_snapshot(items):
    counts = {}
    order = []
    for item in items:
        kind = getattr(item, 'type', '')
        counts[kind] = counts.get(kind, 0) + 1
        order.append({'id': str(item.pk), 'title': getattr(item, 'title', ''),
                      'type': kind, 'number': counts[kind]})
    return {'order': order}


def record_edit(user, obj, action, before, after, source=None):
    if before == after:
        return None
    if isinstance(obj, Course):
        course, lesson, kind = obj, None, 'course'
    elif isinstance(obj, Lesson):
        course, lesson, kind = obj.course, obj, 'lesson'
    else:
        course, lesson, kind = obj.lesson.course, obj.lesson, 'block'
    return CourseEdit.objects.create(
        course=course, actor=user, actor_name=(user.get_full_name() or user.username)[:255],
        kind=kind, action=action, target_id=obj.pk,
        lesson_id=lesson.pk if lesson else None, lesson_title=lesson.title if lesson else '',
        before=before, after=after, source=source,
    )


class EditHistoryMixin:
    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            response = super().create(request, *args, **kwargs)
            if response.status_code == 201:
                obj = self.queryset.model.objects.get(pk=response.data['id'])
                record_edit(request.user, obj, 'created', None, snapshot(obj))
            return response

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            obj = self.get_object()
            before = snapshot(obj)
            response = super().update(request, *args, **kwargs)
            if response.status_code == 200:
                obj.refresh_from_db()
                record_edit(request.user, obj, 'updated', before, snapshot(obj))
            return response

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            obj = self.get_object()
            if not isinstance(obj, Course):
                before = snapshot(obj)
                if isinstance(obj, Lesson):
                    before['blocks'] = [snapshot(block) for block in obj.blocks.order_by('order_index')]
                record_edit(request.user, obj, 'deleted', before, None)
            return super().destroy(request, *args, **kwargs)


def history_context(events, course_id):
    """One batch lookup for numbering of entries recorded before numbers were
    saved. These fallbacks are labelled as current, never as historical facts.
    """
    lessons = {str(pk): index for index, pk in enumerate(Lesson.objects.filter(course_id=course_id)
                .order_by('order_index', 'id').values_list('pk', flat=True), start=1)}
    lesson_ids = {event.lesson_id for event in events if event.lesson_id}
    counts, blocks = {}, {}
    rows = (Block.objects.filter(lesson_id__in=lesson_ids).order_by('order_index', 'id')
            .values_list('pk', 'lesson_id', 'type'))
    for pk, lesson_id, kind in rows:
        key = (lesson_id, kind)
        counts[key] = counts.get(key, 0) + 1
        blocks[str(pk)] = {'type': kind, 'number': counts[key]}
    return {'lessons': lessons, 'blocks': blocks}


def display_snapshot(event, value, context):
    if value is None:
        return None
    value = {**value}
    if event.kind == 'block' and value.get('type') and 'block_number' not in value:
        current = context.get('blocks', {}).get(str(event.target_id))
        if current and current['type'] == value['type']:
            value.update(block_number=current['number'], number_is_current=True)
    if 'lesson_number' not in value and event.lesson_id:
        if event.kind == 'lesson' and value.get('order'):
            position = next((index for index, item in enumerate(value['order'], start=1)
                             if item['id'] == str(event.target_id)), None)
            if position is not None:
                value['lesson_number'] = position
        elif str(event.lesson_id) in context.get('lessons', {}):
            value.update(lesson_number=context['lessons'][str(event.lesson_id)], lesson_number_is_current=True)
    return value


def event_data(event, detail=False, context=None):
    context = context or {}
    before = display_snapshot(event, event.before, context)
    after = display_snapshot(event, event.after, context)
    result = {key: getattr(event, key) for key in ('id', 'actor_name', 'kind', 'action', 'lesson_title')}
    result.update(created_at=event.created_at.isoformat(), target_id=str(event.target_id),
                  lesson_id=str(event.lesson_id) if event.lesson_id else None,
                  source_id=event.source_id)
    value = after or before or {}
    result.update(block_type=value.get('type'), block_number=value.get('block_number'),
                  number_is_current=value.get('number_is_current', False),
                  lesson_number=value.get('lesson_number'),
                  lesson_number_is_current=value.get('lesson_number_is_current', False))
    content = value.get('content') or {}
    text = content.get('html') or content.get('question') or content.get('prompt') or ''
    result['target_label'] = value.get('title') or ' '.join(strip_tags(text).split())[:100] or str(event.target_id)[:8]
    result['changed_fields'] = [key for key in dict.fromkeys([*(event.before or {}), *(event.after or {})])
                                if key not in ('block_number', 'lesson_number')
                                and (event.before or {}).get(key) != (event.after or {}).get(key)]
    if detail:
        result.update(before=before, after=after)
    return result


def history_id(value):
    if not value.isdecimal() or len(value) > 19 or not 0 < int(value) <= 9223372036854775807:
        raise ParseError('Некорректный идентификатор записи.')
    return int(value)


class CourseHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, course_id):
        # Never rely on read-only object permissions: snapshots contain answers.
        if not Course.objects.filter(pk=course_id, author=request.user).exists():
            raise NotFound('Курс не найден.')
        events = CourseEdit.objects.filter(course_id=course_id)
        for field, choices in (('kind', {'course', 'lesson', 'block'}),
                               ('action', {'created', 'updated', 'deleted', 'duplicated', 'reordered', 'restored'})):
            value = request.query_params.get(field)
            if value:
                if value not in choices:
                    raise ParseError('Некорректный фильтр истории.')
                events = events.filter(**{field: value})
        for key, field in (('lesson', 'lesson_id'), ('block', 'target_id')):
            value = request.query_params.get(key)
            if value:
                try:
                    value = uuid.UUID(value)
                except (ValueError, TypeError):
                    raise ParseError('Некорректный идентификатор.')
                events = events.filter(**{field: value})
                if key == 'block':
                    events = events.filter(kind='block')
        event_id = request.query_params.get('event')
        if event_id:
            event = events.filter(pk=history_id(event_id)).first()
            if event is None:
                raise NotFound('Версия не найдена.')
            return Response(event_data(event, detail=True, context=history_context([event], course_id)))
        cursor = request.query_params.get('before')
        if cursor:
            events = events.filter(id__lt=history_id(cursor))
        rows = list(events[:21])
        context = history_context(rows[:20], course_id)
        return Response({'results': [event_data(event, context=context) for event in rows[:20]],
                         'next_cursor': rows[19].id if len(rows) > 20 else None})
