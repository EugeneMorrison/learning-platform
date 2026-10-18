"""
runner/server.py over real HTTP (a server on a free local port, in a thread)
with real interpreters. Plain unittest, no Django; runs on Windows too.

    python -m unittest discover -s runner/tests -t . -v
"""

import http.client
import json
import os
import subprocess
import threading
import time
import unittest
from unittest import mock

from runner import sandbox, server

TOKEN = 'test-token-0123456789abcdef'


class QuietHandler(server.RunHandler):
    def log_message(self, *args):
        pass


def start_server(slots=2, queue_wait=server.QUEUE_WAIT_SECONDS, token=TOKEN):
    httpd = server.RunnerHTTPServer(('127.0.0.1', 0), token, slots, queue_wait=queue_wait)
    httpd.RequestHandlerClass = QuietHandler
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def stop_server(httpd):
    httpd.shutdown()
    httpd.server_close()


def request(httpd, method, path, body=None, headers=None, token=TOKEN):
    """(status, decoded JSON) for one request. `body`: dict (sent as JSON) or bytes."""
    conn = http.client.HTTPConnection('127.0.0.1', httpd.server_address[1], timeout=60)
    try:
        all_headers = {'Content-Type': 'application/json'}
        if token is not None:
            all_headers['Authorization'] = f'Bearer {token}'
        all_headers.update(headers or {})
        if isinstance(body, dict):
            body = json.dumps(body).encode('utf-8')
        conn.request(method, path, body=body, headers=all_headers)
        response = conn.getresponse()
        return response.status, json.loads(response.read().decode('utf-8'))
    finally:
        conn.close()


class ServerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = start_server()

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.httpd)

    def post(self, body, **kwargs):
        return request(self.httpd, 'POST', '/run', body, **kwargs)

    # --- routing and auth ---------------------------------------------------

    def test_health_needs_no_token(self):
        self.assertEqual(request(self.httpd, 'GET', '/health', token=None), (200, {'status': 'ok'}))

    def test_unknown_paths(self):
        self.assertEqual(request(self.httpd, 'GET', '/run')[0], 404)
        self.assertEqual(request(self.httpd, 'POST', '/other', {'code': 'print(1)'})[0], 404)

    def test_token_is_required(self):
        with mock.patch.object(sandbox, 'run_python') as run:
            for token in (None, '', 'wrong-token-0123456789abcdef', TOKEN + 'x', TOKEN[:-1]):
                with self.subTest(token=token):
                    status, body = self.post({'code': 'print(1)'}, token=token)
                    self.assertEqual((status, body), (401, {'error': 'unauthorized'}))
            # Not "Bearer": the right token in another scheme doesn't count.
            status, _ = self.post({'code': 'print(1)'}, token=None,
                                  headers={'Authorization': f'Basic {TOKEN}'})
            self.assertEqual(status, 401)
            run.assert_not_called()

    # --- request validation -------------------------------------------------

    def test_malformed_bodies(self):
        with mock.patch.object(sandbox, 'run_python') as run:
            cases = [
                (b'not json', 'body is not JSON'),
                (b'\xff\xfe', 'body is not JSON'),
                (b'[1, 2]', 'body is not a JSON object'),
                ({'code': 5}, 'code must be a string'),
                ({'code': 'x', 'stdin': None}, 'stdin must be a string'),
                ({'code': 'x', 'version': ['3.12']}, 'version must be a string'),
                ({'code': 'x', 'header': {}}, 'header must be a string'),
                ({'code': 'x', 'footer': 1.5}, 'footer must be a string'),
            ]
            for body, problem in cases:
                with self.subTest(body=body):
                    self.assertEqual(self.post(body), (400, {'error': problem}))
            run.assert_not_called()

    def test_body_size_limits(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=10)
        try:
            # Announced too large: refused before anything is read.
            conn.putrequest('POST', '/run')
            conn.putheader('Authorization', f'Bearer {TOKEN}')
            conn.putheader('Content-Length', str(server.MAX_BODY_BYTES + 1))
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 413)
        finally:
            conn.close()
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_address[1], timeout=10)
        try:
            conn.putrequest('POST', '/run')
            conn.putheader('Authorization', f'Bearer {TOKEN}')
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 411)
        finally:
            conn.close()

    # --- runs ---------------------------------------------------------------

    def test_run_with_stdin_and_unicode(self):
        status, body = self.post({'code': 'print(int(input()) * 2)\nprint("Привет")',
                                  'stdin': '21\n', 'version': 'Python 3.12'})
        self.assertEqual(status, 200)
        self.assertEqual(body, {'returncode': 0, 'stdout': '42\nПривет\n', 'stderr': '',
                                'timed_out': False})

    def test_missing_fields_default_to_empty(self):
        status, body = self.post({'code': 'import sys; print(repr(sys.stdin.read()))'})
        self.assertEqual((status, body['stdout']), (200, "''\n"))

    def test_error_comes_back_with_returncode_and_stderr(self):
        status, body = self.post({'code': 'print(1 / 0)'})
        self.assertEqual(status, 200)
        self.assertNotEqual(body['returncode'], 0)
        self.assertIn('ZeroDivisionError', body['stderr'])
        self.assertFalse(body['timed_out'])

    def test_hidden_code_is_run(self):
        status, body = self.post({'code': 'def double(x):\n    return 2 * x\n',
                                  'header': 'base = 20', 'footer': 'print(double(base + 1))'})
        self.assertEqual((status, body['stdout'], body['returncode']), (200, '42\n', 0))

    def test_timeout(self):
        with mock.patch.object(sandbox, 'TIMEOUT_SECONDS', 1):
            status, body = self.post({'code': 'import time\ntime.sleep(30)'})
        self.assertEqual((status, body), (200, {'returncode': None, 'stdout': '', 'stderr': '',
                                                'timed_out': True}))

    def test_slot_is_passed_to_the_sandbox(self):
        with mock.patch.object(sandbox, 'run_python', return_value=subprocess.CompletedProcess(
                [], 0, 'out', '')) as run:
            status, _ = self.post({'code': 'x', 'stdin': 's', 'version': 'v', 'header': 'h', 'footer': 'f'})
        self.assertEqual(status, 200)
        run.assert_called_once()
        kwargs = run.call_args.kwargs
        self.assertIn(kwargs.pop('slot'), (0, 1))
        self.assertEqual(kwargs, {'code': 'x', 'stdin': 's', 'version': 'v', 'header': 'h', 'footer': 'f'})

    def test_unavailable_and_internal_errors(self):
        with mock.patch.object(sandbox, 'run_python', side_effect=sandbox.RunnerUnavailable('no user')):
            self.assertEqual(self.post({'code': 'x'}), (503, {'error': 'unavailable'}))
        with mock.patch.object(sandbox, 'run_python', side_effect=RuntimeError('secret detail')), \
                mock.patch('traceback.print_exc'):
            # No details of the failure in the response.
            self.assertEqual(self.post({'code': 'x'}), (500, {'error': 'internal'}))
        # Slots were given back: runs still work.
        self.assertEqual(self.post({'code': 'print(1)'})[1]['stdout'], '1\n')


class ConcurrencyTests(unittest.TestCase):
    """RUNNER_SLOTS runs at a time; then a short wait, then 503 busy."""

    def test_busy_when_every_slot_is_taken(self):
        httpd = start_server(slots=1, queue_wait=0.5)
        try:
            first = {}

            def slow():
                first['response'] = request(httpd, 'POST', '/run', {'code': 'import time\ntime.sleep(2)\nprint("slow")'})

            thread = threading.Thread(target=slow)
            thread.start()
            time.sleep(0.5)   # the slow run holds the only slot
            started = time.monotonic()
            self.assertEqual(request(httpd, 'POST', '/run', {'code': 'print(1)'}), (503, {'error': 'busy'}))
            self.assertGreaterEqual(time.monotonic() - started, 0.4)
            thread.join()
            self.assertEqual(first['response'][1]['stdout'], 'slow\n')
            # Free again.
            self.assertEqual(request(httpd, 'POST', '/run', {'code': 'print(2)'})[1]['stdout'], '2\n')
        finally:
            stop_server(httpd)

    def test_waiting_request_gets_the_freed_slot(self):
        httpd = start_server(slots=1, queue_wait=10)
        try:
            results = []
            threads = [threading.Thread(target=lambda n=n: results.append(
                request(httpd, 'POST', '/run', {'code': f'import time\ntime.sleep(0.5)\nprint({n})'})))
                for n in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(sorted(r[1]['stdout'] for r in results), ['0\n', '1\n', '2\n'])
            self.assertEqual({r[0] for r in results}, {200})
        finally:
            stop_server(httpd)


class ConfigTests(unittest.TestCase):

    def test_token_is_mandatory_and_long_enough(self):
        for token in ('', 'short'):
            with self.subTest(token=token), self.assertRaises(server.ConfigError):
                server.check_config(token, 4)
        server.check_config(TOKEN, 4)

    def test_slots_range(self):
        for slots in (0, -1, server.MAX_SLOTS + 1):
            with self.subTest(slots=slots), self.assertRaises(server.ConfigError):
                server.check_config(TOKEN, slots)
        with self.assertRaises(server.ConfigError):
            server.slots_from_env({'RUNNER_SLOTS': 'four'})
        self.assertEqual(server.slots_from_env({}), server.DEFAULT_SLOTS)
        self.assertEqual(server.slots_from_env({'RUNNER_SLOTS': '2'}), 2)

    def test_main_refuses_to_start_without_token(self):
        with self.assertRaises(SystemExit) as cm:
            server.main(['--port', '0'], environ={})
        self.assertIn('RUNNER_TOKEN', str(cm.exception.code))

    @unittest.skipUnless(os.name == 'posix', 'root checks are POSIX only')
    def test_as_root_needs_an_init_and_every_slot_user(self):
        with mock.patch.object(sandbox, 'running_as_root', return_value=True):
            with mock.patch.object(server.os, 'getpid', return_value=1), \
                    self.assertRaisesRegex(server.ConfigError, 'PID 1'):
                server.check_config(TOKEN, 2)
            with mock.patch.object(server.os, 'getpid', return_value=1234), \
                    mock.patch.object(sandbox, 'slot_account',
                                      side_effect=sandbox.RunnerUnavailable('no "runner1" user')), \
                    self.assertRaisesRegex(server.ConfigError, 'runner1'):
                server.check_config(TOKEN, 2)


if __name__ == '__main__':
    unittest.main()
