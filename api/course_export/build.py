"""Read-only extraction and shared writers for request exports."""
from django.db import transaction
from django.db.models import BinaryField, Count, Sum
from django.db.models.functions import Cast, Length

from api.models import Block, Course, Lesson, User
from .access import can_export, can_export_any_course
from .assets import ExportTooLarge
from .downloads import MAX_DOWNLOAD
from .snapshot import extract_course
from .writers import write_mhtml, write_zip


def build(course_id, user_id, fmt, author_materials, stream):
    if fmt not in ('mhtml', 'zip') or (fmt == 'mhtml' and author_materials):
        raise ValueError('Invalid export options')
    user = User.objects.get(pk=user_id)
    course = Course.objects.get(pk=course_id)
    if not can_export(user, course):
        raise PermissionError('Export permission revoked')
    with transaction.atomic():
        sizes = Block.objects.filter(lesson__course_id=course_id).aggregate(
            total=Sum(Length(Cast('content', BinaryField()))), steps=Count('pk'))
        if ((sizes['total'] or 0) + len(course.description.encode()) > 8 * 1024**2
                or sizes['steps'] > 5000 or Lesson.objects.filter(course_id=course_id).count() > 1000):
            raise ExportTooLarge()
        snapshot = extract_course(str(course_id), author_materials, lambda message: None)
        if snapshot['author_id'] != user.pk and not can_export_any_course(user):
            raise PermissionError('Course ownership changed')
    options = dict(warn=lambda message: None, progress=lambda message: None, asset_limit=32 * 1024**2)
    if fmt == 'mhtml':
        write_mhtml(stream, snapshot, **options)
    else:
        write_zip(stream, snapshot, folder_limit=MAX_DOWNLOAD, **options)
