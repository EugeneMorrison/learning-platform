"""
runner/sandbox.py with REAL interpreters. Plain unittest, no Django.

Which tests run where:
- everywhere (Windows dev included): empty environment, isolated mode, own
  temp dir, wall-clock timeout, normal code / stdin, hidden header / footer;
- Linux/macOS: resource limits (memory, output size, leftover processes);
- only as root with the slot users, i.e. in the runner image: slot users,
  file permissions, process limit (fork bomb), processes that leave their
  session, cleanup, no writable directory outside the run, no network.

From the project folder:
    python -m unittest discover -s runner/tests -t . -v
In the runner image (folder /srv), in a separate container:
    docker compose run --rm --no-deps runner python -B -m unittest discover -s runner/tests -t . -v
"""

import json
import os
import re
import subprocess
import sys
import textwrap
import threading
import time
import unittest
from unittest import mock

from runner import sandbox
from runner.sandbox import CHILD_ENV, PYTHON_BINARIES, RunnerUnavailable, run_python

POSIX = os.name == 'posix'


def _slot_uids():
    """uid of each slot user, when running as root in the runner image."""
    if not sandbox.running_as_root():
        return None
    try:
        return [sandbox.slot_account(slot)[0] for slot in (0, 1)]
    except RunnerUnavailable:
        return None


SLOT_UIDS = _slot_uids()
IN_RUNNER_IMAGE = SLOT_UIDS is not None
SLOT = 0 if IN_RUNNER_IMAGE else None
needs_posix = unittest.skipUnless(POSIX, 'resource limits exist on Linux/macOS only')
needs_runner_image = unittest.skipUnless(IN_RUNNER_IMAGE, 'needs root and the slot users (the runner image)')

VERSIONS = list(PYTHON_BINARIES)


def run(code, stdin='', version='Python 3.12', header='', footer='', slot=SLOT):
    return run_python(textwrap.dedent(code), stdin=stdin, version=version,
                      header=textwrap.dedent(header), footer=textwrap.dedent(footer), slot=slot)


def live_processes(uid):
    """PIDs owned by `uid`, zombies (already dead, waiting to be reaped) excluded."""
    pids = []
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            with open(f'/proc/{entry}/status') as f:
                status = dict(line.split(':', 1) for line in f if ':' in line)
        except OSError:
            continue
        if int(status['Uid'].split()[0]) == uid and not status['State'].strip().startswith('Z'):
            pids.append(int(entry))
    return pids


class RunnerBasicsTests(unittest.TestCase):
    """Normal student code works; nothing of the server leaks in."""

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
        marker = {'RUNNER_TOKEN': 'super-secret-for-test', 'RUNNER_TEST_MARKER': 'leak',
                  'PYTHONPATH': '/somewhere', 'PYTHONSTARTUP': '/evil.py'}
        with mock.patch.dict(os.environ, marker):
            result = run("""
                import json, os, sys
                print(json.dumps({'env': dict(os.environ), 'isolated': sys.flags.isolated}))
            """)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertNotIn('RUNNER_TOKEN', data['env'])
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
        self.assertNotEqual(os.path.realpath(workdir), os.path.realpath(os.getcwd()))
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
        self.assertLess(time.monotonic() - started, sandbox.TIMEOUT_SECONDS + 5)

    def test_sleeping_code_is_stopped_by_the_wall_clock(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run('import time\ntime.sleep(60)')

    def test_unknown_version_runs_the_default_interpreter(self):
        result = run('print("ok")', version='Python 2.7')
        self.assertEqual(result.stdout, 'ok\n')


def same_run_dir(text):
    """Tracebacks of two runs differ only in the temporary directory's name."""
    return re.sub(r'run-[^\\/"]+', 'run-X', text)


class RunnerHiddenCodeTests(unittest.TestCase):
    """A CODE block's header / footer (sandbox.LAUNCHER): one program, one
    namespace, and errors never show the hidden source. Each test runs on
    every interpreter offered (both exist only in the runner image)."""

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
        self.assertNotIn(sandbox.LAUNCHER, ' '.join(after.args))
        self.assertIn('main.py', after.args[-1])
        self.assertEqual(same_run_dir(after.stderr), same_run_dir(before.stderr))
        self.assertEqual(after.stdout, "['main.py']\n")


class RunnerFailsClosedTests(unittest.TestCase):
    """As root, code never runs without a slot user."""

    @unittest.skipUnless(POSIX, 'root/user lookup is POSIX only')
    def test_root_without_slot_user_refuses(self):
        import pwd
        with mock.patch('runner.sandbox.os.geteuid', return_value=0), \
                mock.patch.object(pwd, 'getpwnam', side_effect=KeyError('runner0')):
            with self.assertRaises(RunnerUnavailable):
                run('print(1)', slot=0)

    @unittest.skipUnless(POSIX, 'root/user lookup is POSIX only')
    def test_root_without_a_slot_refuses(self):
        with mock.patch('runner.sandbox.os.geteuid', return_value=0):
            with self.assertRaises(RunnerUnavailable):
                run('print(1)', slot=None)


@needs_posix
class RunnerLimitsTests(unittest.TestCase):
    """Resource limits (Linux/macOS)."""

    def test_memory_hog_is_stopped(self):
        result = run('data = bytearray(1024 ** 3)\nprint("allocated")')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('allocated', result.stdout)
        self.assertIn('MemoryError', result.stderr)

    def test_output_flood_is_capped(self):
        result = run("while True:\n    print('x' * 1000)")
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout), sandbox.FILE_BYTES)
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
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)


@needs_runner_image
class RunnerSlotUserTests(unittest.TestCase):
    """Slot users, file permissions, processes, network (runner image only)."""

    @classmethod
    def setUpClass(cls):
        sandbox.lock_shared_dirs()   # what server.main() does at start

    def test_run_directory_is_the_slot_users_alone(self):
        result = run("""
            import os, stat
            st = os.stat('.')
            print(st.st_uid, st.st_gid, oct(stat.S_IMODE(st.st_mode)))
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        uid, gid, mode = result.stdout.split()
        # Owned by the slot user; the server's group may only enter it.
        self.assertEqual((int(uid), int(gid), mode), (SLOT_UIDS[0], os.getegid(), '0o710'))

    def test_runs_as_the_slot_user(self):
        for slot, uid in enumerate(SLOT_UIDS):
            with self.subTest(slot=slot):
                result = run('import os; print(os.getuid(), os.geteuid(), os.getgroups())', slot=slot)
                self.assertEqual(result.stdout.split(maxsplit=2)[:2], [str(uid), str(uid)])
                self.assertNotEqual(uid, 0)
                self.assertEqual(result.stdout.split(maxsplit=2)[2].strip(), '[]')
        self.assertNotEqual(SLOT_UIDS[0], SLOT_UIDS[1])

    def test_cannot_read_the_servers_process(self):
        result = run("""
            import json, os
            out = {}
            for name, path in {'parent_environ': f'/proc/{os.getppid()}/environ',
                               'pid1_environ': '/proc/1/environ',
                               'parent_cwd': f'/proc/{os.getppid()}/cwd/.'}.items():
                try:
                    open(path, 'rb').read(1) if 'environ' in name else os.listdir(path)
                    out[name] = 'ALLOWED'
                except Exception as exc:
                    out[name] = type(exc).__name__
            print(json.dumps(out))
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(set(out.values()), {'PermissionError'}, out)

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
            for d in ('/tmp', '/var/tmp', '/dev/shm', '/dev/mqueue', '/run/lock', '/work', '/srv', '/'):
                try:
                    open(os.path.join(d, 'probe.txt'), 'w').write('x')
                    writable.append('WROTE ' + d)
                except OSError:
                    pass
            print(json.dumps(writable))
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_cannot_see_into_another_slots_run(self):
        """While slot 0 runs, slot 1 can't list /work or reach slot 0's
        processes (cwd, open files: its stdin, stdout)."""
        started = threading.Event()

        def slot0():
            started.set()
            try:
                run('import time\ntime.sleep(3)', slot=0)
            except subprocess.TimeoutExpired:
                pass

        thread = threading.Thread(target=slot0)
        thread.start()
        started.wait()
        time.sleep(1)
        try:
            result = run("""
                import json, os
                me, reached = os.getpid(), []
                try:
                    os.listdir('/work')
                    reached.append('/work')
                except OSError:
                    pass
                for pid in filter(str.isdigit, os.listdir('/proc')):
                    if int(pid) == me:
                        continue
                    for what in ('cwd', 'fd'):
                        try:
                            os.listdir(f'/proc/{pid}/{what}')
                            reached.append(f'{pid}/{what}')
                        except OSError:
                            pass
                print(json.dumps(reached))
            """, slot=1)
        finally:
            thread.join()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_process_that_leaves_its_session_is_killed(self):
        result = run("""
            import os, time
            pid = os.fork()
            if pid == 0:
                os.setsid()
                if os.fork() == 0:
                    time.sleep(60)
                os._exit(0)
            os.waitpid(pid, 0)
            print('started')
        """)
        self.assertEqual(result.stdout, 'started\n')
        time.sleep(0.5)
        self.assertEqual(live_processes(SLOT_UIDS[0]), [])

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
        self.assertLess(time.monotonic() - started, sandbox.TIMEOUT_SECONDS + 10)
        time.sleep(0.5)
        self.assertEqual(live_processes(SLOT_UIDS[0]), [])
        # The slot still works afterwards.
        self.assertEqual(run('print("ok")').stdout.strip(), 'ok')

    def test_locked_directories_are_cleaned_up(self):
        result = run("""
            import os
            os.makedirs('a/b')
            open('a/b/f.txt', 'w').write('x')
            os.symlink('/etc', 'a/link')
            os.chmod('a/b', 0)
            os.chmod('a', 0)
            print(os.getcwd())
            os.chmod('.', 0)
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(result.stdout.strip()))
        self.assertEqual(os.listdir(sandbox.WORK_BASE), [])

    def test_no_network(self):
        result = run("""
            import json, socket
            out = {}
            try:
                socket.getaddrinfo('example.com', 443)
                out['dns'] = 'ALLOWED'
            except OSError as exc:
                out['dns'] = type(exc).__name__
            try:
                socket.create_connection(('1.1.1.1', 443), timeout=2).close()
                out['internet'] = 'ALLOWED'
            except OSError as exc:
                out['internet'] = type(exc).__name__
            print(json.dumps(out))
        """)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertNotIn('ALLOWED', out.values(), out)


if __name__ == '__main__':
    unittest.main()
