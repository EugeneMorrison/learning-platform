"""One bounded export per shared database, retained only for its HTTP request."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import APIException, Throttled

MAX_DOWNLOAD = 96 * 1024**2
GENERATION_SECONDS = 90
DOWNLOAD_SECONDS = 300
DISK_RESERVE = 1024**3


class ExportFailure(APIException):
    status_code = 503
    default_detail = 'Не удалось подготовить файл. Попробуйте ещё раз.'


def check_capacity():
    root = Path(settings.COURSE_EXPORT_ROOT).resolve()
    for public in [settings.MEDIA_ROOT, settings.STATIC_ROOT, *settings.STATICFILES_DIRS]:
        if public and root.is_relative_to(Path(public).resolve()):
            raise ImproperlyConfigured('COURSE_EXPORT_ROOT must be private')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if min(shutil.disk_usage(root).free, shutil.disk_usage(settings.DB_DIR).free) < DISK_RESERVE + MAX_DOWNLOAD:
        raise ExportFailure('Недостаточно свободного места для экспорта.')
    return root


class Lease:
    """OS lock survives threads; kernel releases it on process death."""
    def __init__(self, user_id):
        root = check_capacity()
        self.file = None
        self.lock = open(Path(settings.DB_DIR) / '.course-export.lock', 'a+b')
        try:
            self.lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise Throttled(wait=10, detail='Другой экспорт ещё выполняется. Повторите позже.')
        try:
            self.lock.seek(0)
            raw = self.lock.read(1024 * 1024)
            history = json.loads(raw) if raw else {}
            now = time.time()
            history = {key: [stamp for stamp in stamps if now - stamp < 600]
                       for key, stamps in history.items()}
            history = {key: stamps for key, stamps in history.items() if stamps}
            mine = history.setdefault(str(user_id), [])
            if len(mine) >= 4:
                raise Throttled(wait=max(1, 600 - (now - mine[0])))
            mine.append(now)
            self.lock.seek(0)
            self.lock.truncate()
            self.lock.write(json.dumps(history).encode())
            self.lock.flush()
            self.file = tempfile.TemporaryFile(dir=root, mode='w+b')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.file is not None:
            self.file.close()
        self.lock.close()


async def generate(lease, course_id, user_id, fmt, author_materials):
    options = {}
    if os.name != 'nt':
        # Keep the slot held if the web process dies before the child exits.
        options['pass_fds'] = (lease.lock.fileno(),)
    child = subprocess.Popen(
        [sys.executable, '-m', 'api.course_export.child', str(course_id), str(user_id), fmt,
         '1' if author_materials else '0'], cwd=settings.BASE_DIR,
        stdin=subprocess.DEVNULL, stdout=lease.file, stderr=subprocess.DEVNULL, **options,
    )
    try:
        deadline = time.monotonic() + GENERATION_SECONDS
        while child.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError
            await asyncio.sleep(.1)
        code = child.returncode
        if code:
            raise ExportFailure('Курс превышает ограничения экспорта.' if code == 3 else None)
        size = lease.file.seek(0, 2)
        if not 0 < size <= MAX_DOWNLOAD:
            raise ExportFailure()
        lease.file.seek(0)
    except TimeoutError:
        raise ExportFailure('Подготовка файла заняла слишком много времени. Повторите позже.')
    finally:
        if child.returncode is None:
            child.kill()
            child.wait(timeout=5)
