"""
The code runner's interim lockdown (api/runner.py), with REAL interpreters.

Which tests run where:
- everywhere (Windows dev included): empty environment, isolated mode, own
  temp dir, wall-clock timeout, normal code / stdin / run-tests, the
  SECRET_KEY start-up check;
- Linux/macOS: resource limits (memory, output size, leftover processes);
- only as root with the "runner" user, i.e. inside the Docker image: the
  unprivileged user, file permissions, process limit (fork bomb), no
  writable directory outside the run directory.

In the container (see the report for the full command):
    docker compose run --rm -e SECRET_KEY=test web python manage.py test api.test_runner -v 2
"""

import json
import os
import re
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from . import runner
from .models import Block, Course, Enrollment, Lesson, User
from .runner import CHILD_ENV, PYTHON_BINARIES, RUNNER_USER, RunnerUnavailable, run_python

POSIX = os.name == 'posix'


def _runner_uid():
    if not POSIX or os.geteuid() != 0:
        return None
    import pwd
    try:
        return pwd.getpwnam(RUNNER_USER).pw_uid
    except KeyError:
        return None


RUNNER_UID = _runner_uid()
needs_posix = unittest.skipUnless(POSIX, 'resource limits exist on Linux/macOS only')
needs_runner_user = unittest.skipUnless(
    RUNNER_UID is not None, f'needs root and the "{RUNNER_USER}" user (the Docker image)')

VERSIONS = list(PYTHON_BINARIES)


def run(code, stdin='', version='Python 3.12', header='', footer=''):
    return run_python(textwrap.dedent(code), stdin=stdin, version=version,
                      header=textwrap.dedent(header), footer=textwrap.dedent(footer))


def runner_processes():
    """PIDs owned by the runner user (Linux /proc)."""
    pids = []
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            try:
                if entry.stat().st_uid == RUNNER_UID:
                    pids.append(int(entry.name))
            except FileNotFoundError:
                pass
    return pids


class RunnerBasicsTests(SimpleTestCase):
    """Normal student code still works; nothing of the server leaks in."""

    def test_code_and_stdin_on_both_versions(self):
        code = """
            import sys
            a, b = int(input()), int(input())
            print(a + b)
            print('Привет')
            print(sys.version_info[:2])
        """
        for version in VERSIONS:
            with self.subTest(version=version):
                result = run(code, stdin='2\n3\n', version=version)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(lines[:2], ['5', 'Привет'])
                # Where the image's interpreters exist, each version really runs.
                if os.path.exists(PYTHON_BINARIES[version]):
                    expected = tuple(int(n) for n in version.split()[1].split('.'))
                    self.assertEqual(lines[2], str(expected))

    def test_errors_come_back_as_stderr(self):
        result = run('print(1 / 0)')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ZeroDivisionError', result.stderr)

    def test_child_sees_no_server_environment(self):
        marker = {'SECRET_KEY': 'super-secret-for-test', 'RUNNER_TEST_MARKER': 'leak',
                  'PYTHONPATH': '/somewhere', 'PYTHONSTARTUP': '/evil.py'}
        with mock.patch.dict(os.environ, marker):
            result = run("""
                import json, os, sys
                print(json.dumps({'env': dict(os.environ), 'isolated': sys.flags.isolated}))
            """)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertNotIn('SECRET_KEY', data['env'])
        self.assertNotIn('RUNNER_TEST_MARKER', data['env'])
        self.assertNotIn('super-secret-for-test', json.dumps(data['env']))
        # Only what the runner passes (plus what an OS adds on its own).
        self.assertLessEqual(set(data['env']) - set(CHILD_ENV),
                             {'__CF_USER_TEXT_ENCODING', 'LC_CTYPE', 'SYSTEMROOT', 'COMSPEC'})
        self.assertEqual(data['isolated'], 1)

    def test_runs_in_a_fresh_temp_dir_that_is_deleted(self):
        result = run("""
            import os
            open('note.txt', 'w').write('mine')
            print(os.getcwd())
            print(sorted(os.listdir('.')))
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        workdir, listing = result.stdout.splitlines()
        self.assertEqual(listing, str(['main.py', 'note.txt']))
        self.assertFalse(os.path.exists(workdir))
        self.assertNotEqual(Path(workdir).resolve(), Path(settings.BASE_DIR).resolve())
        # The next run starts empty.
        again = run("import os; print(sorted(os.listdir('.')))")
        self.assertEqual(again.stdout.strip(), str(['main.py']))

    def test_infinite_loop_is_stopped(self):
        started = time.monotonic()
        try:
            result = run('while True:\n    pass')
        except subprocess.TimeoutExpired:
            result = None
        # Either the wall clock (TimeoutExpired) or the CPU limit stops it.
        if result is not None:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Time limit exceeded', result.stderr)
        self.assertLess(time.monotonic() - started, runner.TIMEOUT_SECONDS + 5)

    def test_sleeping_code_is_stopped_by_the_wall_clock(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run('import time\ntime.sleep(60)')


def same_run_dir(text):
    """Tracebacks of two runs differ only in the temporary directory's name."""
    return re.sub(r'run-[^\\/"]+', 'run-X', text)


class RunnerHiddenCodeTests(SimpleTestCase):
    """A CODE block's header / footer (runner.LAUNCHER): one program, one
    namespace, and errors never show the hidden source. Each test runs on
    every interpreter offered (both exist only in the Docker image)."""

    SECRET = 'MARK-HIDDEN-SOURCE'
    HEADER = f"""
        import math
        class Point:
            def __init__(self, x, y):
                self.x, self.y = x, y  # {SECRET}
    """  # 5 lines: the leading blank line counts

    def test_header_code_footer_share_one_namespace(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                result = run("""
                    def dist(p):
                        return math.hypot(p.x, p.y)
                """, header=self.HEADER, footer='print(dist(Point(3, 4)))', version=version)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '5.0\n')

    def test_student_error_reports_their_own_line(self):
        code = 'x = 1\nprint(1 / 0)\n'
        for version in VERSIONS:
            with self.subTest(version=version):
                result = run(code, header=self.HEADER, version=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('main.py", line 2, in <module>', result.stderr)
                self.assertIn('print(1 / 0)', result.stderr)
                # The very traceback a run without hidden code prints.
                plain = run(code, version=version)
                self.assertEqual(same_run_dir(result.stderr), same_run_dir(plain.stderr))

    def test_student_syntax_error_reports_their_own_line(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                result = run('x = 1\ndef f(:\n', header=self.HEADER,
                             footer='print("footer ran")', version=version)
                self.assertIn('main.py", line 2', result.stderr)
                self.assertIn('SyntaxError', result.stderr)
                self.assertEqual(result.stdout, '')  # nothing runs

    def test_footer_error_hides_its_source_and_the_launcher(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                result = run("""
                    def area(p):
                        return p.x / p.y
                """, header=self.HEADER, footer=f"""
                    print(area(Point(1, 2)))
                    print(area(Point(1, 0)))  # {self.SECRET}
                """, version=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '0.5\n')
                stderr = result.stderr
                self.assertIn('ZeroDivisionError', stderr)
                # The checker's frame (no source), then the student's (with source).
                self.assertIn('File "<hidden>", line 3, in <module>', stderr)
                self.assertIn('main.py", line 3, in area', stderr)
                self.assertIn('return p.x / p.y', stderr)
                self.assertNotIn(self.SECRET, stderr)
                self.assertNotIn('print(area', stderr)
                for launcher in ('_launch', 'exec(', '<string>', 'hidden.json'):
                    self.assertNotIn(launcher, stderr)

    def test_hidden_exception_chain_hides_every_source_line(self):
        result = run('pass', footer=f"""
            try:
                {{}}['key']  # {self.SECRET}
            except KeyError as exc:
                raise ValueError('checker failed') from exc  # {self.SECRET}
        """)
        self.assertIn('KeyError', result.stderr)
        self.assertIn('ValueError: checker failed', result.stderr)
        self.assertNotIn(self.SECRET, result.stderr)

    def test_hidden_syntax_error_hides_the_line(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                result = run('print("student")', header=f'def broken(:  # {self.SECRET}\n',
                             version=version)
                self.assertIn('SyntaxError', result.stderr)
                self.assertIn('File "<hidden>", line 1', result.stderr)
                self.assertNotIn(self.SECRET, result.stderr)
                self.assertNotIn('broken', result.stderr)
                self.assertEqual(result.stdout, '')

    def test_program_sees_what_a_plain_run_sees(self):
        probe = """
            import json, os, sys, __main__
            print(json.dumps([sorted(globals()), __name__, os.path.basename(__file__),
                              sys.argv, type(__loader__).__name__, __spec__, __cached__,
                              __main__.__dict__ is globals(), sorted(os.listdir('.'))]))
        """
        for version in VERSIONS:
            with self.subTest(version=version):
                hidden = run(probe, header='x_from_header = 1', version=version)
                plain = run('x_from_header = 1\n' + textwrap.dedent(probe), version=version)
                self.assertEqual(hidden.returncode, 0, hidden.stderr)
                # Same globals, __main__, argv, loader; hidden.json already gone.
                self.assertEqual(json.loads(hidden.stdout), json.loads(plain.stdout))

    def test_exit_ends_the_program_before_the_footer(self):
        result = run('import sys\nprint("student")\nsys.exit(3)', footer='print("footer")')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, 'student\n')
        self.assertEqual(result.stderr, '')

    def test_stdin_reaches_the_program(self):
        result = run('n = int(input())', header='data = [1, 2, 3]',
                     footer='print(data[n])', stdin='2\n')
        self.assertEqual(result.stdout, '3\n')

    def test_timeout_covers_the_whole_run(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run('print("student")', footer='import time\ntime.sleep(60)')

    def test_without_hidden_code_nothing_changes(self):
        code = 'import os\nprint(sorted(os.listdir(".")))\nprint(1 / 0)\n'
        before = run(code)
        after = run(code, header='', footer='')
        # The very same command: python main.py, no launcher.
        self.assertEqual(before.args, after.args)
        self.assertNotIn(runner.LAUNCHER, ' '.join(after.args))
        self.assertIn('main.py', after.args[-1])
        self.assertEqual(same_run_dir(after.stderr), same_run_dir(before.stderr))
        self.assertEqual(after.stdout, "['main.py']\n")


@needs_posix
class RunnerLimitsTests(SimpleTestCase):
    """Resource limits (Linux/macOS)."""

    def test_memory_hog_is_stopped(self):
        result = run('data = bytearray(1024 ** 3)\nprint("allocated")')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('allocated', result.stdout)
        self.assertIn('MemoryError', result.stderr)

    def test_output_flood_is_capped(self):
        result = run("while True:\n    print('x' * 1000)")
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout), runner.FILE_BYTES)
        # A clear reason, not the raw EFBIG traceback the cap causes.
        self.assertIn('Output limit exceeded', result.stderr)
        self.assertNotIn('Errno 27', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_large_file_is_capped(self):
        result = run("open('big.bin', 'wb').write(b'x' * (5 * 1024 ** 2))\nprint('written')")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('written', result.stdout)
        self.assertIn('File size limit exceeded', result.stderr)

    def test_forked_children_do_not_outlive_the_run(self):
        result = run("""
            import os, time
            pid = os.fork()
            if pid == 0:
                time.sleep(60)
                os._exit(0)
            print(pid)
        """)
        child = int(result.stdout.strip())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)


@needs_runner_user
class RunnerUserTests(SimpleTestCase):
    """The unprivileged user and the image's file permissions (Docker only)."""

    def test_runs_as_the_runner_user(self):
        result = run('import os; print(os.getuid(), os.getgid(), os.getgroups())')
        uid, gid, groups = result.stdout.split(maxsplit=2)
        self.assertEqual(int(uid), RUNNER_UID)
        self.assertNotEqual(int(uid), 0)
        self.assertEqual(groups.strip(), '[]')

    def test_cannot_read_database_code_media_or_env(self):
        # The REAL production paths. Not settings.DATABASES: during tests
        # Django replaces its NAME with the in-memory test database.
        app = Path(settings.BASE_DIR)
        files = {
            'database': Path(settings.DB_DIR) / 'db.sqlite3',
            'code': app / 'backend' / 'settings.py',
            'env': app / '.env',
            'media_file': Path(settings.MEDIA_ROOT) / 'runner-probe.txt',
            'pid1_environ': Path('/proc/1/environ'),
        }
        dirs = {'app': app, 'db_dir': Path(settings.DB_DIR), 'media': Path(settings.MEDIA_ROOT)}

        # Something real to read: dummies where the test container has none
        # (removed afterwards; existing files are never touched).
        created = []
        for name in ('database', 'env', 'media_file'):
            path = files[name]
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'dummy for test_cannot_read_database_code_media_or_env')
                created.append(path)
        try:
            probes = {name: ('read', str(p)) for name, p in files.items()}
            probes.update({name: ('list', str(p)) for name, p in dirs.items()})
            result = run(f"""
                import json, os
                out = {{}}
                for name, (how, path) in {probes!r}.items():
                    try:
                        if how == 'read':
                            open(path, 'rb').read(1)
                        else:
                            os.listdir(path)
                        out[name] = 'ALLOWED'
                    except Exception as exc:
                        out[name] = type(exc).__name__
                print(json.dumps(out))
            """)
        finally:
            for path in created:
                path.unlink()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(set(out), set(probes))
        # Every item, not just the first failure: all mismatches at once.
        failures = {name: f'{outcome} ({probes[name][0]} {probes[name][1]})'
                    for name, outcome in out.items() if outcome != 'PermissionError'}
        self.assertEqual(failures, {})

    def test_cannot_write_outside_its_run_directory(self):
        result = run("""
            import json, os
            here = os.getcwd()
            writable = []
            def walk(path):
                try:
                    entries = list(os.scandir(path))
                except OSError:
                    return
                for e in entries:
                    if e.is_dir(follow_symlinks=False) and e.path not in ('/proc', '/sys'):
                        if os.access(e.path, os.W_OK) and not e.path.startswith(here):
                            writable.append(e.path)
                        walk(e.path)
            walk('/')
            # And really try the usual suspects.
            for d in ('/tmp', '/var/tmp', '/dev/shm', '/run/lock', '/app', '/var/lib/runner'):
                try:
                    open(os.path.join(d, 'probe.txt'), 'w').write('x')
                    writable.append('WROTE ' + d)
                except OSError:
                    pass
            print(json.dumps(writable))
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_fork_bomb_is_stopped_and_cleaned_up(self):
        started = time.monotonic()
        try:
            run("""
                import os
                while True:
                    try:
                        os.fork()
                    except OSError:
                        pass
            """)
        except subprocess.TimeoutExpired:
            pass
        self.assertLess(time.monotonic() - started, runner.TIMEOUT_SECONDS + 5)
        time.sleep(0.5)
        self.assertEqual(runner_processes(), [])
        # The runner still works afterwards.
        self.assertEqual(run('print("ok")').stdout.strip(), 'ok')


class RunnerFailsClosedTests(APITestCase):
    """As root without the runner user, code is never run (503)."""

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
        self.client.force_authenticate(self.student)

    @unittest.skipUnless(POSIX, 'root/user lookup is POSIX only')
    def test_root_without_runner_user_refuses(self):
        import pwd
        with mock.patch('api.runner.os.geteuid', return_value=0), \
                mock.patch.object(pwd, 'getpwnam', side_effect=KeyError(RUNNER_USER)):
            with self.assertRaises(RunnerUnavailable):
                run('print(1)')

    def test_api_returns_503_when_the_runner_is_unavailable(self):
        with mock.patch('api.runner._runner_account', side_effect=RunnerUnavailable('test')):
            for url in ('/api/run-code/', '/api/run-tests/'):
                response = self.client.post(url, {'block_id': str(self.block.id), 'code': 'print(1)',
                                                  'stdin': '', 'version': 'Python 3.12'}, format='json')
                self.assertEqual(response.status_code, 503, url)

    def test_run_code_and_run_tests_end_to_end(self):
        code = 'a = int(input())\nb = int(input())\nprint(a + b)'
        for version in VERSIONS:
            with self.subTest(version=version):
                response = self.client.post('/api/run-code/', {
                    'block_id': str(self.block.id), 'code': code, 'stdin': '7\n8\n',
                    'version': version}, format='json')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['stdout'].strip(), '15')
                response = self.client.post('/api/run-tests/', {
                    'block_id': str(self.block.id), 'code': code, 'version': version}, format='json')
                self.assertEqual(response.data['status'], 'success', response.data)


class HiddenCodeEndToEndTests(APITestCase):
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


class SecretKeyStartupTests(SimpleTestCase):
    """Without DEBUG the server refuses to start unless SECRET_KEY is set."""

    def start(self, **env):
        clean = {k: v for k, v in os.environ.items() if k not in ('SECRET_KEY', 'DEBUG')}
        clean.update(env, DJANGO_SETTINGS_MODULE='backend.settings')
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
