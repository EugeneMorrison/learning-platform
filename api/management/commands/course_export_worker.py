"""Process dashboard exports outside the web server. Uses no external broker."""
import logging
import shutil
import subprocess
import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import IntegrityError, close_old_connections, transaction

from api.course_export import jobs
from api.course_export.assets import ExportTooLarge
from api.models import CourseExportJob


log = logging.getLogger(__name__)


def run_child(job):
    return subprocess.run(
        [sys.executable, str(settings.BASE_DIR / 'manage.py'), 'course_export_worker', '--build', str(job.pk)],
        stdin=subprocess.DEVNULL, timeout=jobs.BUILD_SECONDS, check=False,
    ).returncode


def process_one():
    job = CourseExportJob.objects.filter(state='queued').order_by('created_at', 'pk').first()
    if not job:
        return False
    try:
        with transaction.atomic():
            claimed = jobs.transition(job, 'queued', 'running')
    except IntegrityError:
        return False  # Another worker holds the single running slot.
    if not claimed:
        return False
    workspace = None
    try:
        jobs.check_capacity()
        output = jobs.artifact(job)
        workspace = output.with_suffix('.work')
        workspace.mkdir(mode=0o700)
        code = run_child(job)
        if code == 3:
            raise ExportTooLarge()
        if code:
            raise RuntimeError(f'Export child exited with status {code}')
        (workspace / 'download').replace(output)
        if not jobs.transition(job, 'running', 'ready'):
            jobs.remove_file(output)
    except Exception as error:
        log.exception('Course export %s failed', job.pk)
        message = 'Не удалось подготовить файл. Попробуйте ещё раз.'
        if isinstance(error, ExportTooLarge):
            message = jobs.SIZE_ERROR
        elif isinstance(error, jobs.StorageUnavailable):
            message = str(error.detail)
        elif isinstance(error, subprocess.TimeoutExpired):
            message = jobs.TIME_ERROR
        jobs.transition(job, 'running', 'failed', message)
    finally:
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)  # The sweep also retries after a worker crash.
    return True


class Command(BaseCommand):
    help = 'Generate queued dashboard course downloads and expire private artifacts.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Sweep and process at most one job.')
        parser.add_argument('--build', metavar='JOB_ID', help='Internal child-process entry point.')

    def handle(self, *args, **options):
        if options['build']:
            if sys.platform.startswith('linux'):
                import resource
                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2,) * 2)
                resource.setrlimit(resource.RLIMIT_FSIZE, (jobs.MAX_DOWNLOAD,) * 2)
            job = CourseExportJob.objects.select_related('course', 'requester').defer('course__description').get(
                pk=options['build'], state='running')
            try:
                jobs.build(job, jobs.private_root() / (job.id.hex + '.work'))
            except (ExportTooLarge, MemoryError):
                raise SystemExit(3)
            return
        next_sweep = 0
        while True:
            close_old_connections()
            if time.monotonic() >= next_sweep:
                jobs.sweep()
                next_sweep = time.monotonic() + 15
            worked = process_one()
            if options['once']:
                return
            if not worked:
                time.sleep(1)
