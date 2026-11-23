import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile
from email import policy
from email.parser import BytesParser
from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import AsyncRequestFactory, TransactionTestCase, override_settings
from rest_framework.test import force_authenticate
from api.models import Block, Course, Enrollment, Lesson, Progress, User
from api.course_export import downloads
from api.course_export.build import build
from api.course_export.views import export_course


class DashboardExportTests(TransactionTestCase):
    @classmethod
    def create_fixtures(cls):
        cls.owner = User.objects.create(username='author', role='AUTHOR')
        cls.student = User.objects.create(username='private-student')
        cls.other = User.objects.create(username='other', role='AUTHOR')
        cls.admin = User.objects.create(username='operator', is_superuser=True, is_staff=True)
        cls.course = Course.objects.create(author=cls.owner, title='Paid course', price=1200)
        Enrollment.objects.create(course=cls.course, student=cls.student)
        locked = Lesson.objects.create(course=cls.course, title='Paid lesson', order_index=2)
        Lesson.objects.create(course=cls.course, title='Preview', order_index=1, is_preview=True)
        code = Block.objects.create(lesson=locked, type='CODE', order_index=1, content={
            'prompt': 'Paid exercise', 'solution': 'OFFICIAL', 'tests': [
                {'input': 'secret input', 'expected': 'hidden', 'visible': False}]})
        Block.objects.create(lesson=locked, type='TEXT', order_index=2, content={
            'html': '<p>Paid theory</p><img src="/media/picture.png">'})
        Progress.objects.create(student=cls.student, lesson=locked, block=code, answer={'code': 'STUDENT_WORK'})


    def setUp(self):
        self.create_fixtures()
        self.temp = self.enterContext(TemporaryDirectory())
        self.root = Path(self.temp)
        self.media = self.root / 'media'
        self.media.mkdir()
        (self.media / 'picture.png').write_bytes(b'image-content')
        self.enterContext(override_settings(DB_DIR=self.root, COURSE_EXPORT_ROOT=self.root / 'private',
                                           MEDIA_ROOT=self.media))
        from django.core.cache import cache
        cache.clear()
        self.base = f'/api/courses/{self.course.pk}/exports/'

    async def request(self, fmt='zip', private=False, user='owner'):
        request = AsyncRequestFactory().post(self.base,
            json.dumps({'format': fmt, 'author_materials': private}), content_type='application/json')
        if user is not None:
            force_authenticate(request, self.owner if user == 'owner' else user)
        return await export_course(request, course_id=self.course.pk)

    async def generate(self, lease, course_id, user_id, fmt, private):
        await sync_to_async(build)(course_id, user_id, fmt, private, lease.file)
        lease.file.seek(0)

    def download(self, fmt='zip', private=False, user='owner'):
        async def run():
            with patch.object(downloads, 'generate', side_effect=self.generate):
                response = await self.request(fmt, private, user)
                self.assertEqual(response.status_code, 200)
                self.assertIn('paid-course-', response['Content-Disposition'])
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                data = b''.join([chunk async for chunk in response.streaming_content])
                self.assertTrue(response.lease.file.closed)
                self.assertTrue(response.lease.lock.closed)
                response.close()
                return data
        return async_to_sync(run)()

    def test_zip_complete_paid_content_and_author_protection(self):
        for private in (False, True):
            with ZipFile(BytesIO(self.download(private=private))) as archive:
                self.assertIsNone(archive.testzip())
                manifest = json.loads(archive.read('course.json'))
                self.assertEqual(manifest['audience'], 'author' if private else 'learner')
                lessons = [json.loads(archive.read(name)) for name in manifest['lessons']]
                self.assertEqual([lesson['title'] for lesson in lessons], ['Preview', 'Paid lesson'])
                names = [name for name in archive.namelist() if name.endswith('.step')]
                self.assertTrue(names[0].endswith('01_code.step'))
                content = b''.join(archive.read(name) for name in names).decode()
                self.assertIn('Paid exercise', content)
                self.assertEqual('OFFICIAL' in content, private)
                self.assertEqual('secret input' in content, private)
                self.assertNotIn('STUDENT_WORK', content)
                self.assertEqual(archive.read(manifest['assets']['/media/picture.png']), b'image-content')

    def test_mhtml_paid_content_and_assets(self):
        message = BytesParser(policy=policy.default).parsebytes(self.download('mhtml'))
        _, document, image = message.iter_parts()
        self.assertEqual(image.get_payload(decode=True), b'image-content')
        for value in ('Paid exercise', 'Paid theory', 'Preview', 'Paid lesson'):
            self.assertIn(value, document.get_content())
        for value in ('OFFICIAL', 'secret input', 'STUDENT_WORK', 'private-student'):
            self.assertNotIn(value, document.get_content())

    def test_permissions_and_validation(self):
        staff = User.objects.create(username='staff', is_staff=True)
        for user in (None, self.student, self.other, staff):
            response = async_to_sync(self.request)(user=user)
            self.assertEqual(response.status_code, 401 if user is None else 404)
        for fmt, private in (('../bad', False), ('mhtml', True)):
            self.assertEqual(async_to_sync(self.request)(fmt, private).status_code, 400)
        self.download(user=self.admin, private=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='api', codename='export_any_course'))
        self.download(user=User.objects.get(pk=staff.pk), private=True)

    def test_revocation_before_download(self):
        async def revoke(*args):
            await self.generate(*args)
            await sync_to_async(Course.objects.filter(pk=self.course.pk).update)(author=self.other)
        with patch.object(downloads, 'generate', side_effect=revoke):
            self.assertEqual(async_to_sync(self.request)().status_code, 404)
        self.assertEqual(list((self.root / 'private').iterdir()), [])

    def test_single_slot_includes_download_and_cleanup(self):
        async def run():
            with patch.object(downloads, 'generate', side_effect=self.generate):
                first = await self.request()
                self.assertEqual((await self.request()).status_code, 429)
                iterator = first.streaming_content
                self.assertLessEqual(len(await anext(iterator)), 65536)
                await iterator.aclose()
                first.close()  # Django's ASGI handler closes the response on disconnect.
                self.assertTrue(first.lease.file.closed)
                second = await self.request()
                self.assertEqual(second.status_code, 200)
                second.close()
        async_to_sync(run)()

    def test_rate_limit_survives_separate_requests(self):
        for _ in range(4):
            self.download()
        self.assertEqual(async_to_sync(self.request)().status_code, 429)

    def test_generation_failure_and_disconnect_cleanup(self):
        async def fail(lease, *args):
            lease.file.write(b'partial')
            raise downloads.ExportFailure()
        with patch.object(downloads, 'generate', side_effect=fail):
            self.assertEqual(async_to_sync(self.request)().status_code, 503)
        async def cancel(lease, *args):
            lease.file.write(b'partial')
            raise asyncio.CancelledError()
        with patch.object(downloads, 'generate', side_effect=cancel):
            with self.assertRaises(asyncio.CancelledError):
                async_to_sync(self.request)()
        self.download()
        self.assertEqual(list((self.root / 'private').iterdir()), [])

    def test_download_deadline_closes_unconsumed_response(self):
        async def run():
            with patch.object(downloads, 'generate', side_effect=self.generate), patch.object(downloads, 'DOWNLOAD_SECONDS', .01):
                response = await self.request()
                await asyncio.sleep(.03)
                self.assertTrue(response.lease.file.closed)
                self.assertTrue(response.lease.lock.closed)
        async_to_sync(run)()

    def test_disk_and_public_storage_guards(self):
        from types import SimpleNamespace
        from django.core.exceptions import ImproperlyConfigured
        with patch.object(downloads.shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
            self.assertEqual(async_to_sync(self.request)().status_code, 503)
        with override_settings(COURSE_EXPORT_ROOT=self.media / 'exports'):
            with self.assertRaises(ImproperlyConfigured):
                downloads.check_capacity()

    def test_asgi_disconnect_cleans_generation_and_active_download(self):
        from django.core.asgi import get_asgi_application
        from rest_framework_simplejwt.tokens import AccessToken
        token = str(AccessToken.for_user(self.owner))

        async def run(during_generation):
            received = asyncio.Queue()
            reached = asyncio.Event()
            leases = []

            async def generate(lease, *args):
                leases.append(lease)
                if during_generation:
                    reached.set()
                    await asyncio.Future()
                lease.file.write(b'x' * 200000)
                lease.file.seek(0)

            async def send(message):
                if message['type'] == 'http.response.body':
                    reached.set()
                    if not leases:
                        raise AssertionError(message.get('body', b'')[:500])
                    await asyncio.Future()  # Simulate backpressure from a slow browser.

            scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                'method': 'POST', 'scheme': 'http', 'path': self.base, 'query_string': b'',
                'headers': [(b'host', b'testserver'), (b'content-type', b'application/json'), (b'content-length', b'16'),
                            (b'authorization', ('Bearer ' + token).encode())],
                'server': ('testserver', 80), 'client': ('127.0.0.1', 1234)}
            await received.put({'type': 'http.request', 'body': b'{"format":"zip"}', 'more_body': False})
            with patch.object(downloads, 'generate', side_effect=generate):
                task = asyncio.create_task(get_asgi_application()(scope, received.get, send))
                try:
                    await asyncio.wait_for(reached.wait(), 10)
                    await received.put({'type': 'http.disconnect'})
                    await asyncio.wait_for(task, 10)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(len(leases), 1)
            self.assertTrue(leases[0].file.closed)
            self.assertTrue(leases[0].lock.closed)

        for during_generation in (True, False):
            async_to_sync(run)(during_generation)

    def test_oversized_archive_and_inactive_owner_are_denied(self):
        from api.course_export.assets import ExportTooLarge
        with patch('api.course_export.build.MAX_DOWNLOAD', 10):
            with BytesIO() as stream, self.assertRaises(ExportTooLarge):
                build(self.course.pk, self.owner.pk, 'zip', False, stream)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        inactive = User.objects.get(pk=self.owner.pk)
        self.assertEqual(async_to_sync(self.request)(user=inactive).status_code, 404)

    def test_actual_child_and_output_integrity(self):
        copy_path = self.root / 'db.sqlite3'
        with sqlite3.connect(copy_path) as copied:
            connection.connection.backup(copied)
        copied.close()
        for fmt in ('zip', 'mhtml'):
            with TemporaryDirectory() as temp, open(Path(temp) / 'download', 'w+b') as target:
                result = subprocess.run(
                    [sys.executable, '-m', 'api.course_export.child', str(self.course.pk),
                     str(self.owner.pk), fmt, '0'],
                    cwd=settings.BASE_DIR, env={**os.environ, 'DB_DIR': str(self.root)},
                    stdout=target, stderr=subprocess.PIPE, timeout=90)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                target.seek(0)
                if fmt == 'zip':
                    with ZipFile(target) as archive:
                        self.assertIsNone(archive.testzip())
                else:
                    self.assertEqual(BytesParser(policy=policy.default).parse(target).get_content_type(), 'multipart/related')

    def test_generation_deadline_and_cancellation_reap_child(self):
        original = subprocess.Popen
        children = []

        def sleeping_child(*args, **kwargs):
            child = original([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            children.append(child)
            return child

        async def run():
            with patch.object(downloads.subprocess, 'Popen', side_effect=sleeping_child):
                with patch.object(downloads, 'GENERATION_SECONDS', .01):
                    response = await self.request()
                    self.assertEqual(response.status_code, 503)
                task = asyncio.create_task(self.request())
                while len(children) < 2:
                    await asyncio.sleep(.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertEqual(list((self.root / 'private').iterdir()), [])
        async_to_sync(run)()

    def test_another_process_cannot_acquire_active_slot(self):
        with override_settings(DB_DIR=self.root):
            lease = downloads.Lease(self.owner.pk)
            try:
                code = ('import os; os.environ["DJANGO_SETTINGS_MODULE"]="backend.settings"; '
                        'from api.course_export.downloads import Lease; Lease(999)')
                child = subprocess.run([sys.executable, '-c', code], cwd=settings.BASE_DIR,
                    env={**os.environ, 'DB_DIR': str(self.root), 'COURSE_EXPORT_ROOT': str(self.root / 'private')},
                    capture_output=True, timeout=30)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn(b'Throttled', child.stderr)
            finally:
                lease.close()

    def test_queue_retirement_preserves_course_and_permission_grants(self):
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        executor.migrate([('api', '0025_course_export_job')])
        try:
            apps = executor.loader.project_state([('api', '0025_course_export_job')]).apps
            content_type, _ = apps.get_model('contenttypes', 'ContentType').objects.get_or_create(
                app_label='api', model='courseexportjob')
            permission = Permission.objects.get(codename='export_any_course', content_type__app_label='api')
            permission.content_type_id = content_type.pk
            permission.save()
            self.admin.user_permissions.add(permission)
            executor = MigrationExecutor(connection)
            executor.migrate([('api', '0026_retire_course_export_queue')])
            permission.refresh_from_db()
            self.assertEqual(permission.content_type.model, 'course')
            self.assertTrue(self.admin.user_permissions.filter(pk=permission.pk).exists())
            self.assertTrue(Course.objects.filter(pk=self.course.pk).exists())
            self.assertNotIn('api_courseexportjob', connection.introspection.table_names())
        finally:
            MigrationExecutor(connection).migrate([('api', '0026_retire_course_export_queue')])
