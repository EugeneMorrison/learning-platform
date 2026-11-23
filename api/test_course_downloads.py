import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import AsyncRequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, force_authenticate

from api.course_export import jobs
from api.course_export.assets import Assets, ExportTooLarge
from api.course_export.views import ExportDownloadView
from api.management.commands import course_export_worker as worker
from api.models import Block, Course, CourseExportJob, Enrollment, Lesson, Progress, User


class DashboardExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
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
        temp = self.enterContext(TemporaryDirectory())
        self.root = Path(temp) / 'private'
        media = Path(temp) / 'media'
        media.mkdir()
        (media / 'picture.png').write_bytes(b'image-content')
        self.enterContext(override_settings(COURSE_EXPORT_ROOT=self.root, MEDIA_ROOT=media,
                                            COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE=False))
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.base = f'/api/courses/{self.course.pk}/exports/'

    def start(self, fmt='zip', private=False):
        response = self.client.post(self.base, {'format': fmt, 'author_materials': private}, format='json')
        self.assertEqual(response.status_code, 202, response.data)
        return CourseExportJob.objects.get(pk=response.data['id'])

    def run_job(self):
        def child(job):
            jobs.build(job, self.root / (job.id.hex + '.work'))
            return 0
        with patch.object(worker, 'run_child', side_effect=child):
            self.assertTrue(worker.process_one())

    def download(self, job):
        url = self.base + str(job.pk) + '/'
        self.assertEqual(self.client.get(url).data['state'], 'ready')
        response = self.client.post(url + 'download/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('paid-course-', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])
        data = b''.join(response.streaming_content)
        response.close()
        self.assertFalse(jobs.artifact(job).exists())
        self.assertEqual(self.client.post(url + 'download/').status_code, 409)
        return data

    def test_zip_contains_full_paid_course_and_explicit_author_materials_only(self):
        for private in [False, True]:
            job = self.start(private=private)
            self.run_job()
            with ZipFile(BytesIO(self.download(job))) as z:
                manifest = json.loads(z.read('course.json'))
                self.assertEqual(manifest['audience'], 'author' if private else 'learner')
                lessons = [json.loads(z.read(p)) for p in manifest['lessons']]
                self.assertEqual([l['title'] for l in lessons], ['Preview', 'Paid lesson'])
                paths = [PurePosixPath(manifest['lessons'][1]).parent / step for step in lessons[1]['steps']]
                self.assertEqual([p.name for p in paths], ['01_code.step', '02_text.step'])
                self.assertEqual(z.read(manifest['assets']['/media/picture.png']), b'image-content')
                content = json.loads(z.read(str(paths[0])))['content']
                self.assertEqual(content['prompt'], 'Paid exercise')
                self.assertEqual('OFFICIAL' in str(content), private)
                self.assertEqual('secret input' in str(content), private)
                self.assertNotIn('STUDENT_WORK', b''.join(z.read(p) for p in z.namelist()).decode())

    def test_paid_mhtml_offline_body_and_asset(self):
        job = self.start('mhtml')
        self.run_job()
        _, document, image = BytesParser(policy=policy.default).parsebytes(self.download(job)).iter_parts()
        self.assertEqual(image.get_payload(decode=True), b'image-content')
        body = document.get_content()
        for label in ['Preview', 'Paid lesson', 'Paid exercise', 'Paid theory']:
            self.assertIn(label, body)
        for secret in ['OFFICIAL', 'secret input', 'STUDENT_WORK', 'private-student']:
            self.assertNotIn(secret, body)

    def test_permissions_checked_at_all_endpoints_including_after_transfer(self):
        job = self.start(private=True)
        self.run_job()
        url = self.base + str(job.pk) + '/'
        staff = User.objects.create(username='staff', is_staff=True, role='ADMIN')
        for user in [None, self.student, self.other, staff]:
            self.client.force_authenticate(user=user)
            expected = 404 if user else 401
            self.assertEqual(self.client.post(self.base, {'format': 'zip'}).status_code, expected)
            self.assertEqual(self.client.get(url).status_code, expected)
            self.assertEqual(self.client.post(url + 'download/').status_code, expected)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(url).status_code, 404)  # Private even between authorized operators.
        self.assertTrue(self.client.get(self.base.removesuffix('exports/')).data['can_export'])
        admin_job = self.start()
        self.run_job()
        self.download(admin_job)
        Course.objects.filter(pk=self.course.pk).update(author=self.other)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(url + 'download/').status_code, 404)

    def test_pending_deduplication_and_rate_limits(self):
        job = self.start()
        self.assertEqual(self.start().pk, job.pk)
        self.assertEqual(self.client.post(self.base, {'format': 'mhtml'}).status_code, 429)
        for _ in range(3):
            CourseExportJob.objects.filter(state='queued').update(state='failed')
            self.start()
        CourseExportJob.objects.filter(state='queued').update(state='failed')
        self.assertEqual(self.client.post(self.base, {'format': 'zip'}).status_code, 429)
        self.assertEqual(CourseExportJob.objects.count(), 4)

    def test_delegated_staff_permission_is_required_again_at_download(self):
        operator = User.objects.create(username='export-admin', is_staff=True)
        permission = Permission.objects.get(content_type__app_label='api', codename='export_any_course')
        operator.user_permissions.add(permission)
        self.client.force_authenticate(operator)
        job = self.start(private=True)
        self.run_job()
        self.assertEqual(CourseExportJob.objects.get(pk=job.pk).state, 'ready')
        operator.user_permissions.remove(permission)
        self.client.force_authenticate(User.objects.get(pk=operator.pk))  # A fresh JWT-authenticated request.
        self.assertEqual(self.client.post(self.base + str(job.pk) + '/download/').status_code, 404)

    def test_queue_capacity_and_single_worker_slot(self):
        CourseExportJob.objects.bulk_create([
            CourseExportJob(course=self.course, requester=self.other, format='zip', state='ready')
            for _ in range(12)
        ])
        self.assertEqual(self.client.post(self.base, {'format': 'mhtml'}).status_code, 429)
        CourseExportJob.objects.all().delete()
        CourseExportJob.objects.create(course=self.course, requester=self.other, format='zip', state='running')
        pending = self.start()
        with patch.object(worker, 'run_child') as child:
            self.assertFalse(worker.process_one())
            child.assert_not_called()
        pending.refresh_from_db()
        self.assertEqual(pending.state, 'queued')

    def test_rejects_invalid_options_and_public_storage(self):
        from django.core.exceptions import ImproperlyConfigured
        for options in [{'format': '../course'}, {'format': 'mhtml', 'author_materials': True}]:
            self.assertEqual(self.client.post(self.base, options, format='json').status_code, 400)
        with override_settings(COURSE_EXPORT_ROOT=self.root.parent / 'media' / 'exports'):
            with self.assertRaises(ImproperlyConfigured):
                jobs.private_root()

    def test_failed_or_timed_out_child_removes_partial_files(self):
        for code in [1, 3, 'timeout']:
            job = self.start()
            def fail(current):
                (self.root / (current.id.hex + '.work') / 'download').write_bytes(b'partial')
                if code == 'timeout':
                    raise subprocess.TimeoutExpired('child', 180)
                return code
            with self.assertLogs(worker.log, level='ERROR'), patch.object(worker, 'run_child', side_effect=fail):
                self.assertTrue(worker.process_one())
            job.refresh_from_db()
            self.assertEqual(job.state, 'failed')
            self.assertNotIn('partial', job.error)
            self.assertEqual(list(self.root.iterdir()), [])

    def test_expiry_and_orphan_cleanup(self):
        job = self.start()
        self.run_job()
        CourseExportJob.objects.update(updated_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(self.client.post(self.base + str(job.pk) + '/download/').status_code, 409)
        jobs.sweep()
        self.assertFalse(jobs.artifact(job).exists())
        self.assertEqual(CourseExportJob.objects.get().state, 'failed')
        job = self.start()
        working = self.root / (job.id.hex + '.work')
        working.mkdir()
        job.delete()
        jobs.sweep()
        self.assertFalse(working.exists())

    def test_asgi_streams_chunks_and_closes_after_interrupted_download(self):
        job = self.start()
        jobs.artifact(job).write_bytes(b'x' * 200000)
        CourseExportJob.objects.update(state='ready')
        request = AsyncRequestFactory().post(self.base)
        force_authenticate(request, self.owner)
        response = ExportDownloadView.as_view()(request, course_id=self.course.pk, job_id=job.pk)
        self.assertTrue(response.is_async)

        async def first_chunk():
            return await anext(aiter(response))
        self.assertEqual(len(async_to_sync(first_chunk)()), 65536)
        response.close()
        self.assertFalse(jobs.artifact(job).exists())

    def test_oversized_assets_fail_without_producing_an_incomplete_archive(self):
        with self.assertRaises(ExportTooLarge):
            Assets(self.fail, byte_limit=2).resolve('/media/picture.png', 'test')

    def test_production_storage_refuses_missing_and_same_device_spools(self):
        with override_settings(COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE=True, DB_DIR=self.root.parent):
            for exists in (False, True):
                if exists:
                    self.root.mkdir()
                with self.assertLogs(jobs.log, level='ERROR'):
                    self.assertEqual(self.client.post(self.base, {'format': 'zip'}).status_code, 503)
                self.assertEqual(self.root.exists(), exists)
            self.assertFalse(CourseExportJob.objects.exists())

    def test_low_disk_blocks_admission_and_build_but_allows_cleanup(self):
        enough = SimpleNamespace(free=2 * jobs.DB_RESERVE)
        low = SimpleNamespace(free=1)
        job = self.start()
        for usage in ([low], [enough, low]):
            with patch.object(jobs.shutil, 'disk_usage', side_effect=usage):
                self.assertEqual(self.client.post(self.base, {'format': 'zip'}).status_code, 503)
        with patch.object(jobs.shutil, 'disk_usage', return_value=low), patch.object(worker, 'run_child') as child:
            with self.assertLogs(worker.log, level='ERROR'):
                self.assertTrue(worker.process_one())
            child.assert_not_called()
            job.refresh_from_db()
            self.assertEqual(job.state, 'failed')
            jobs.artifact(job).write_bytes(b'orphan')
            jobs.sweep()
            self.assertFalse(jobs.artifact(job).exists())

    def test_cumulative_folder_limit_cleans_staging_before_zip(self):
        job = self.start()
        with patch.object(jobs, 'MAX_DOWNLOAD', 100), self.assertLogs(worker.log, level='ERROR'):
            self.run_job()
        job.refresh_from_db()
        self.assertEqual(job.error, jobs.SIZE_ERROR)
        self.assertEqual(list(self.root.iterdir()), [])


class ExportSubprocessTests(TransactionTestCase):
    def test_worker_builds_against_an_isolated_database_in_a_real_child(self):
        owner = User.objects.create(username='writer', role='AUTHOR')
        course = Course.objects.create(author=owner, title='Worker smoke test')
        with TemporaryDirectory() as temp, closing(sqlite3.connect(str(Path(temp) / 'db.sqlite3'))) as copy:
            root = Path(temp) / 'spool'
            with override_settings(COURSE_EXPORT_ROOT=root, COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE=False):
                job = jobs.enqueue(course, owner, 'zip', False)
            connection.connection.backup(copy)
            subprocess.run(
                [sys.executable, str(settings.BASE_DIR / 'manage.py'), 'course_export_worker', '--once'],
                env={**os.environ, 'DB_DIR': temp, 'COURSE_EXPORT_ROOT': str(root),
                     'COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE': '0'},
                timeout=60, check=True,
            )
            self.assertEqual(copy.execute('SELECT state FROM api_courseexportjob WHERE id=?',
                                          (job.id.hex,)).fetchone(), ('ready',))
            with ZipFile(root / job.id.hex) as archive:
                self.assertEqual(json.loads(archive.read('course.json'))['id'], str(course.pk))
