"""
The web side of the code runner: api/runner.py (the HTTP client and the local
development fallback) and the run endpoints, against a REAL runner server.

The runner's own tests (sandbox limits, slot users, HTTP server) are in
runner/tests/. Here the runner is runner/server.py started in a thread on a
free local port; where the runner/ folder isn't there (the web image), the
end-to-end tests use the real runner from RUNNER_URL / RUNNER_TOKEN instead,
and skip without one.

    python manage.py test api.test_runner -v 2
"""

import json
import os
import socket
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .runner import RunnerBusy, RunnerUnavailable, run_python

try:
    from runner import sandbox as runner_sandbox, server as runner_server
except ImportError:   # the web image has no runner/ folder
    runner_sandbox = runner_server = None

TOKEN = 'test-token-0123456789abcdef'
VERSIONS = ['Python 3.10', 'Python 3.12']


needs_runner_folder = unittest.skipUnless(runner_server is not None, 'needs the runner/ folder')


def start_runner(slots=2, queue_wait=10):
    """runner/server.py in a thread, without access logs; returns (server, url)."""
    httpd = runner_server.RunnerHTTPServer(('127.0.0.1', 0), TOKEN, slots, queue_wait=queue_wait)
    httpd.RequestHandlerClass = type('QuietHandler', (runner_server.RunHandler,),
                                     {'log_message': lambda self, *args: None})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f'http://127.0.0.1:{httpd.server_address[1]}/run'


def stop_runner(httpd):
    httpd.shutdown()
    httpd.server_close()


class FakeRunner:
    """A stand-in runner that gives every request the same (status, body)
    answer and records what it received."""

    def __init__(self, status=200, body=b'{}'):
        fake = self
        self.status, self.body, self.requests = status, body, []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                fake.requests.append({'path': self.path, 'headers': dict(self.headers),
                                      'body': self.rfile.read(length)})
                self.send_response(fake.status)
                self.send_header('Content-Length', str(len(fake.body)))
                self.end_headers()
                self.wfile.write(fake.body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}/run'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class LiveRunnerMixin:
    """The tests in this class talk to a real runner: runner/server.py in a
    thread, or else the configured one (RUNNER_URL), or they skip."""

    @classmethod
    def setUpClass(cls):
        cls.runner_httpd = None
        if runner_server is not None:
            cls.runner_httpd, url = start_runner()
            token = TOKEN
        elif settings.RUNNER_URL and settings.RUNNER_TOKEN:
            url, token = settings.RUNNER_URL, settings.RUNNER_TOKEN
        else:
            raise unittest.SkipTest('no runner: no runner/ folder and no RUNNER_URL')
        cls.runner_settings = override_settings(RUNNER_URL=url, RUNNER_TOKEN=token)
        cls.runner_settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.runner_settings.disable()
        if cls.runner_httpd is not None:
            stop_runner(cls.runner_httpd)


# --- api/runner.py ------------------------------------------------------------

class RunnerClientTests(LiveRunnerMixin, SimpleTestCase):
    """run_python() over HTTP: the same results as when code ran in-process."""

    def test_output_and_returncode(self):
        result = run_python('print(int(input()) + 1)\nprint("Привет")', stdin='41\n')
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '42\nПривет\n', ''))

    def test_error(self):
        result = run_python('print(1 / 0)')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ZeroDivisionError', result.stderr)

    def test_hidden_code(self):
        result = run_python('def f(x):\n    return x * 2\n', header='n = 21', footer='print(f(n))')
        self.assertEqual(result.stdout, '42\n')

    def test_fields_must_be_strings(self):
        for kwargs in ({'code': 5}, {'code': 'x', 'stdin': None}, {'code': 'x', 'header': []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TypeError):
                run_python(**kwargs)

    def test_requests_never_use_a_proxy(self):
        bogus = 'http://127.0.0.1:9'
        with mock.patch.dict(os.environ, {'HTTP_PROXY': bogus, 'http_proxy': bogus, 'NO_PROXY': '', 'no_proxy': ''}):
            self.assertEqual(run_python('print(1)').stdout, '1\n')


@needs_runner_folder
class RunnerClientErrorTests(SimpleTestCase):
    """How the runner's answers and failures map to exceptions."""

    def test_sends_only_the_run_fields_with_the_token(self):
        answer = json.dumps({'returncode': 0, 'stdout': 'ok', 'stderr': '', 'timed_out': False})
        with FakeRunner(body=answer.encode()) as fake, \
                override_settings(RUNNER_URL=fake.url, RUNNER_TOKEN=TOKEN):
            result = run_python('code', stdin='in', version='Python 3.10', header='h', footer='f')
        self.assertEqual((result.returncode, result.stdout), (0, 'ok'))
        [sent] = fake.requests
        self.assertEqual(sent['path'], '/run')
        self.assertEqual(sent['headers']['Authorization'], f'Bearer {TOKEN}')
        self.assertEqual(json.loads(sent['body']), {
            'code': 'code', 'stdin': 'in', 'version': 'Python 3.10', 'header': 'h', 'footer': 'f'})

    def test_timed_out_run_raises_timeout_expired(self):
        answer = json.dumps({'returncode': None, 'stdout': '', 'stderr': '', 'timed_out': True})
        with FakeRunner(body=answer.encode()) as fake, \
                override_settings(RUNNER_URL=fake.url, RUNNER_TOKEN=TOKEN):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_python('x')

    def test_timeout_with_the_real_runner(self):
        httpd, url = start_runner()
        try:
            with override_settings(RUNNER_URL=url, RUNNER_TOKEN=TOKEN), \
                    mock.patch.object(runner_sandbox, 'TIMEOUT_SECONDS', 1):
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_python('import time\ntime.sleep(30)')
        finally:
            stop_runner(httpd)

    def test_busy_runner_raises_runner_busy(self):
        httpd, url = start_runner(slots=1, queue_wait=0.3)
        try:
            with override_settings(RUNNER_URL=url, RUNNER_TOKEN=TOKEN):
                slow = threading.Thread(target=run_python, args=('import time\ntime.sleep(2)',))
                slow.start()
                threading.Event().wait(0.5)   # the slow run holds the only slot
                try:
                    with self.assertRaises(RunnerBusy):
                        run_python('print(1)')
                finally:
                    slow.join()
        finally:
            stop_runner(httpd)

    def test_failures_raise_runner_unavailable(self):
        cases = [
            (503, b'{"error": "unavailable"}'),
            (500, b'{"error": "internal"}'),
            (401, b'{"error": "unauthorized"}'),
            (502, b'<html>bad gateway</html>'),
            (200, b'not json'),
            (200, b'[1, 2]'),
            (200, b'{"returncode": 0, "stderr": "", "timed_out": false}'),
            (200, b'{"returncode": "0", "stdout": "", "stderr": "", "timed_out": false}'),
            (200, b'{"returncode": true, "stdout": "", "stderr": "", "timed_out": false}'),
        ]
        for status, body in cases:
            with self.subTest(status=status, body=body), FakeRunner(status, body) as fake, \
                    override_settings(RUNNER_URL=fake.url, RUNNER_TOKEN=TOKEN):
                with self.assertRaises(RunnerUnavailable) as cm:
                    run_python('x')
                self.assertNotIsInstance(cm.exception, RunnerBusy)

    def test_wrong_token_with_the_real_runner(self):
        httpd, url = start_runner()
        try:
            with override_settings(RUNNER_URL=url, RUNNER_TOKEN='wrong-token-0123456789abcdef'):
                with self.assertRaises(RunnerUnavailable):
                    run_python('print(1)')
        finally:
            stop_runner(httpd)

    def test_runner_not_listening(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        with override_settings(RUNNER_URL=f'http://127.0.0.1:{port}/run', RUNNER_TOKEN=TOKEN):
            with self.assertRaises(RunnerUnavailable):
                run_python('print(1)')

    def test_token_is_required(self):
        with FakeRunner() as fake, override_settings(RUNNER_URL=fake.url, RUNNER_TOKEN=''):
            with self.assertRaises(RunnerUnavailable):
                run_python('print(1)')
        self.assertEqual(fake.requests, [])


class InProcessFallbackTests(SimpleTestCase):
    """No RUNNER_URL: in-process only for local development (DEBUG on)."""

    @override_settings(DEBUG=False, RUNNER_URL='')
    def test_production_without_runner_url_refuses(self):
        with self.assertRaises(RunnerUnavailable):
            run_python('print(1)')

    @needs_runner_folder
    @override_settings(DEBUG=True, RUNNER_URL='')
    def test_development_runs_in_process(self):
        result = run_python('print(int(input()) * 2)', stdin='21')
        self.assertEqual((result.returncode, result.stdout), (0, '42\n'))

    @override_settings(DEBUG=True, RUNNER_URL='')
    def test_development_without_runner_folder_refuses(self):
        # As in the web image: no runner/ to import.
        with mock.patch.dict(sys.modules, {'runner': None, 'runner.sandbox': None}):
            with self.assertRaises(RunnerUnavailable):
                run_python('print(1)')


# --- the run endpoints ----------------------------------------------------------

class RunEndpointsTestData:

    @classmethod
    def setUpTestData(cls):
        author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        course = Course.objects.create(title='C', author=author, is_published=True)
        lesson = Lesson.objects.create(course=course, title='L', order_index=1)
        cls.block = Block.objects.create(lesson=lesson, type='CODE', order_index=1, content={
            'prompt': 'p', 'starter_code': '',
            'tests': [{'input': '2\n3', 'expected': '5'}, {'input': '10\n-4', 'expected': '6'}]})
        Enrollment.objects.create(student=cls.student, course=course)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # runner throttle counters
        self.client.force_authenticate(self.student)

    def post(self, url, code='a = int(input())\nb = int(input())\nprint(a + b)', **extra):
        return self.client.post(url, {'block_id': str(self.block.id), 'code': code,
                                      'stdin': '7\n8\n', 'version': 'Python 3.12', **extra}, format='json')


class RunnerBusyAndUnavailableTests(RunEndpointsTestData, APITestCase):
    """503 when code couldn't run; nothing is recorded."""

    def test_busy(self):
        with mock.patch('api.views.run_python', side_effect=RunnerBusy()):
            for url in ('/api/run-code/', '/api/run-tests/'):
                response = self.post(url)
                self.assertEqual(response.status_code, 503, url)
                self.assertEqual(response.data, {'error': 'Code runner is busy, try again'})
        self.assertEqual((Progress.objects.count(), Attempt.objects.count()), (0, 0))

    def test_busy_between_tests_records_nothing(self):
        passed = subprocess.CompletedProcess([], 0, '5\n', '')
        with mock.patch('api.views.run_python', side_effect=[passed, RunnerBusy()]):
            response = self.post('/api/run-tests/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual((Progress.objects.count(), Attempt.objects.count()), (0, 0))

    def test_unavailable(self):
        with mock.patch('api.views.run_python', side_effect=RunnerUnavailable('test')):
            for url in ('/api/run-code/', '/api/run-tests/'):
                response = self.post(url)
                self.assertEqual(response.status_code, 503, url)
                self.assertEqual(response.data, {'error': 'Code runner is not available'})
        self.assertEqual((Progress.objects.count(), Attempt.objects.count()), (0, 0))

    @override_settings(DEBUG=False, RUNNER_URL='')
    def test_production_without_runner_url_is_unavailable(self):
        for url in ('/api/run-code/', '/api/run-tests/'):
            self.assertEqual(self.post(url).status_code, 503, url)


class RunEndpointsEndToEndTests(LiveRunnerMixin, RunEndpointsTestData, APITestCase):
    """The run endpoints through a real runner."""

    def test_run_code_and_run_tests(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                response = self.post('/api/run-code/', version=version)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['stdout'].strip(), '15')
                response = self.post('/api/run-tests/', version=version)
                self.assertEqual(response.data['status'], 'success', response.data)
        self.assertTrue(Progress.objects.get(student=self.student, block=self.block).is_correct)

    def test_wrong_answer_is_graded_here(self):
        response = self.post('/api/run-tests/', code='print(5)')
        self.assertEqual((response.data['status'], response.data['test_number']), ('wrong_answer', 2))
        self.assertFalse(Progress.objects.get(student=self.student, block=self.block).is_correct)

    def test_expected_outputs_never_reach_the_runner(self):
        sent = []
        real = run_python

        def spy(code, **kwargs):
            sent.append((code, kwargs))
            return real(code, **kwargs)

        with mock.patch('api.views.run_python', side_effect=spy):
            self.post('/api/run-tests/')
        self.assertEqual(len(sent), 2)
        for code, kwargs in sent:
            self.assertEqual(set(kwargs), {'stdin', 'version', 'header', 'footer'})
            self.assertNotIn('expected', json.dumps(kwargs))


class HiddenCodeEndToEndTests(LiveRunnerMixin, APITestCase):
    """/api/run-tests/ and /api/run-code/ with a block's hidden header / footer,
    real interpreters (Stepik-style task: the footer calls the student's code)."""

    SECRET = 'MARK-FOOTER-SOURCE'

    @classmethod
    def setUpTestData(cls):
        author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        course = Course.objects.create(title='C', author=author, is_published=True)
        lesson = Lesson.objects.create(course=course, title='L', order_index=1)
        cls.block = Block.objects.create(lesson=lesson, type='CODE', order_index=1, content={
            'prompt': 'p', 'starter_code': 'def dist(p):\n    pass\n',
            'header': 'class Point:\n    def __init__(self, x, y):\n        self.x, self.y = x, y\n',
            'footer': f'x, y = map(int, input().split())\nprint(dist(Point(x, y)))  # {cls.SECRET}\n',
            'tests': [{'input': '3 4', 'expected': '5.0', 'visible': True},
                      {'input': '6 8', 'expected': '10.0', 'visible': True}]})
        Enrollment.objects.create(student=cls.student, course=course)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # runner throttle counters
        self.client.force_authenticate(self.student)

    def post(self, url, code, **extra):
        return self.client.post(url, {'block_id': str(self.block.id), 'code': code,
                                      'version': 'Python 3.12', **extra}, format='json')

    def test_grading_runs_header_code_footer(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                response = self.post('/api/run-tests/', 'def dist(p):\n    return (p.x ** 2 + p.y ** 2) ** 0.5\n',
                                     version=version)
                self.assertEqual(response.data['status'], 'success', response.data)
                self.assertEqual(response.data['passed'], 2)

    def test_student_error_shows_their_line_and_no_hidden_source(self):
        response = self.post('/api/run-tests/', 'def dist(p):\n    return p.z\n')
        self.assertEqual((response.data['status'], response.data['test_number']), ('error', 1))
        stderr = response.data['stderr']
        self.assertIn('main.py", line 2, in dist', stderr)
        self.assertIn("AttributeError: 'Point' object has no attribute 'z'", stderr)
        self.assertNotIn(self.SECRET, stderr)
        self.assertNotIn('print(dist', stderr)

    def test_run_button_runs_the_stored_footer(self):
        response = self.post('/api/run-code/', 'def dist(p):\n    return p.x + p.y\n',
                             stdin='1 2\n', header='raise SystemExit("evil")')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data['stdout'], response.data['stderr']), ('3\n', ''))


# Everything the server needs with DEBUG off besides SECRET_KEY (no real SMTP
# server is contacted: these tests only start Django). The email startup
# checks themselves are in api/test_email_settings.py.
EMAIL_ENV = dict(EMAIL_HOST='smtp.example.com', EMAIL_PORT='465', EMAIL_USE_SSL='True',
                 DEFAULT_FROM_EMAIL='noreply@example.com', SITE_URL='https://example.com')


class SecretKeyStartupTests(SimpleTestCase):
    """Without DEBUG the server refuses to start unless SECRET_KEY is set."""

    def start(self, **env):
        clean = {k: v for k, v in os.environ.items() if k not in ('SECRET_KEY', 'DEBUG')}
        clean.update(EMAIL_ENV, **env, DJANGO_SETTINGS_MODULE='backend.settings')
        return subprocess.run(
            [sys.executable, '-c', 'import django; django.setup(); print("started")'],
            cwd=settings.BASE_DIR, env=clean, capture_output=True, text=True, timeout=60)

    def test_refuses_without_secret_key_when_debug_is_off(self):
        result = self.start(DEBUG='False')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SECRET_KEY is not set', result.stderr)

    def test_starts_with_secret_key(self):
        result = self.start(DEBUG='False', SECRET_KEY='set-for-this-test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('started', result.stdout)

    def test_no_key_in_the_settings_file(self):
        source = (Path(settings.BASE_DIR) / 'backend' / 'settings.py').read_text(encoding='utf-8')
        self.assertNotIn('django-insecure-', source)
