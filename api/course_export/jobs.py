"""Private dashboard export queue and artifact lifecycle (single shared SQLite database)."""
import logging
import shutil
from datetime import timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import BinaryField, Count, Sum
from django.db.models.functions import Cast, Length
from django.utils import timezone
from rest_framework.exceptions import APIException, Throttled
from slugify import slugify

from api.models import Block, Course, CourseExportJob, Lesson
from .access import can_export, can_export_any_course
from .assets import ExportTooLarge
from .snapshot import extract_course
from .writers import write_folder, write_mhtml

log = logging.getLogger(__name__)
READY_TTL = timedelta(minutes=15)
QUEUE_TTL = timedelta(minutes=10)
BUILD_SECONDS = 180
MAX_DOWNLOAD = 96 * 1024 * 1024
SPOOL_RESERVE = 256 * 1024**2
DB_RESERVE = 1024**3
SIZE_ERROR = 'Курс слишком большой для скачивания через сайт.'
TIME_ERROR = 'Время ожидания истекло. Запустите экспорт ещё раз.'


class StorageUnavailable(APIException):
    status_code = 503
    default_detail = 'Хранилище экспорта недоступно. Попробуйте позже.'


def private_root():
    root = Path(settings.COURSE_EXPORT_ROOT).resolve()
    for directory in [settings.MEDIA_ROOT, settings.STATIC_ROOT, *settings.STATICFILES_DIRS]:
        if directory and root.is_relative_to(Path(directory).resolve()):
            raise ImproperlyConfigured('COURSE_EXPORT_ROOT must be private.')
    if settings.COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE:
        if not root.is_dir() or root.stat().st_dev == Path(settings.DB_DIR).stat().st_dev:
            log.error('Export storage requires a mounted filesystem separate from SQLite.')
            raise StorageUnavailable()
    else:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def check_capacity():
    try:
        root = private_root()
        if (shutil.disk_usage(root).free < SPOOL_RESERVE + 2 * MAX_DOWNLOAD
                or shutil.disk_usage(settings.DB_DIR).free < DB_RESERVE):
            raise StorageUnavailable()
        return root
    except OSError as exc:
        raise StorageUnavailable() from exc


def artifact(job):
    return private_root() / job.id.hex


def filename(job):
    name = slugify(job.course.slug, max_length=48) or 'course'
    suffix = '-author' if job.author_materials else ''
    return f'{name}-{job.course_id}{suffix}.{job.format}'


@transaction.atomic
def enqueue(course, user, fmt, author_materials):
    now = timezone.now()
    check_capacity()
    # Insert first: competing SQLite transactions acquire the write lock before
    # counting. An admission failure rolls back this provisional row.
    job = CourseExportJob.objects.create(course=course, requester=user, format=fmt, author_materials=author_materials)
    others = CourseExportJob.objects.exclude(pk=job.pk)
    mine = others.filter(requester=user)
    active = mine.filter(state__in=['queued', 'running'])
    existing = mine.filter(course=course, format=fmt, author_materials=author_materials).filter(
        state__in=['queued', 'running', 'ready'], updated_at__gt=now - READY_TTL).first()
    if existing:
        job.delete()
        return existing
    if active.exists():
        raise Throttled(detail='Дождитесь завершения текущего экспорта.')
    if mine.filter(created_at__gt=now - QUEUE_TTL).count() >= 4:
        raise Throttled(detail='Лимит экспортов исчерпан. Попробуйте через 10 минут.')
    if others.filter(state__in=['queued', 'running', 'ready']).count() >= 12:
        raise Throttled(detail='Очередь экспорта заполнена. Попробуйте позже.')
    return job


def build(job, workspace):
    """Runs in a bounded child process. Only the worker publishes the result."""
    if not can_export(job.requester, job.course):
        raise PermissionError('Export permission revoked')
    with transaction.atomic():
        blocks = Block.objects.filter(lesson__course_id=job.course_id)
        size = blocks.aggregate(total=Sum(Length(Cast('content', BinaryField()))), steps=Count('pk'))
        description_size = Course.objects.filter(pk=job.course_id).values_list(
            Length(Cast('description', BinaryField())), flat=True).get()
        content_size = (size['total'] or 0) + description_size
        lessons = Lesson.objects.filter(course_id=job.course_id).count()
        if content_size > 8 * 1024 * 1024 or size['steps'] > 5000 or lessons > 1000:
            raise ExportTooLarge()
        snapshot = extract_course(str(job.course_id), job.author_materials, log.warning)
        if job.requester_id != snapshot['author_id'] and not can_export_any_course(job.requester):
            raise PermissionError('Course ownership changed')
    result = workspace / 'download'
    options = {'warn': log.warning, 'progress': lambda message: None, 'asset_limit': 32 * 1024 * 1024}
    if job.format == 'mhtml':
        write_mhtml(result, snapshot, **options)
    else:
        folder = workspace / 'course'
        write_folder(folder, snapshot, folder_limit=MAX_DOWNLOAD, **options)
        with ZipFile(result, 'w', compression=ZIP_DEFLATED, compresslevel=3) as archive:
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(folder).as_posix())
    if result.stat().st_size > MAX_DOWNLOAD:
        raise ExportTooLarge()


def transition(job, expected, state, error=''):
    return CourseExportJob.objects.filter(pk=job.pk, state=expected).update(
        state=state, error=error, updated_at=timezone.now())


def remove_file(path):
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        # Windows keeps an open download locked. The next sweep retries.
        log.debug('Export still open: %s', path.name)


def sweep():
    root = private_root()
    now = timezone.now()
    jobs = CourseExportJob.objects
    for state, age in [('queued', QUEUE_TTL), ('running', timedelta(seconds=BUILD_SECONDS + 60)),
                       ('ready', READY_TTL)]:
        jobs.filter(state=state, updated_at__lt=now - age).update(state='failed', error=TIME_ERROR, updated_at=now)
    jobs.filter(state__in=['failed', 'downloaded'], updated_at__lt=now - READY_TTL).delete()
    # Also collect orphans after process death or cascading DB deletes. Only
    # touch entries with our exact UUID naming convention in the private spool.
    for path in root.iterdir():
        name = path.name.removesuffix('.work')
        if len(name) != 32 or any(c not in '0123456789abcdef' for c in name):
            continue
        if path.name.endswith('.work'):
            if not jobs.filter(pk=name, state='running').exists():
                try:
                    shutil.rmtree(path)
                except FileNotFoundError:
                    pass  # The supervisor has already cleaned its workspace.
                except PermissionError:
                    log.warning('Could not remove export workspace %s; will retry', name)
        elif not jobs.filter(pk=name, state__in=['ready', 'running']).exists():
            remove_file(path)
