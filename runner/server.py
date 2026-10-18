"""
The code runner's HTTP server: runs student Python code for the web service
(api/runner.py), one run per request, in its own container (runner/Dockerfile,
docker-compose.yml). Standard library only.

    POST /run    Authorization: Bearer <RUNNER_TOKEN>    Content-Type: application/json
    {"code": str, "stdin": str, "version": str, "header": str, "footer": str}
    → 200 {"returncode": int | null, "stdout": str, "stderr": str, "timed_out": bool}
      400 malformed body · 401 bad token · 404 unknown path · 411 no Content-Length
      413 body over MAX_BODY_BYTES · 503 {"error": "busy"} no free slot within
      QUEUE_WAIT_SECONDS · 503 {"error": "unavailable"} can't run safely · 500
    GET /health → 200 {"status": "ok"}   (no token: the container healthcheck)

Every field is optional and defaults to "". Expected outputs never come here:
the web service compares them itself.

Concurrency: RUNNER_SLOTS runs at a time, each in its own slot, whose user
runs the code (runner/sandbox.py). A request waits up to QUEUE_WAIT_SECONDS
for a free slot, then gets 503 busy.

The token is required: student code shares this container's network, so
without it a run could call this server itself and start more runs, around
the web service's login, enrollment and rate limits. Student code can't read
it: it runs as another user, with an empty environment.

Configuration: only RUNNER_TOKEN (required, at least 16 characters) and
RUNNER_SLOTS (default 4) from the environment; --host / --port on the command
line (default 127.0.0.1:8001; the container listens on 0.0.0.0).

As root (the container) it refuses to start when it would be PID 1 (orphans
of killed runs would never be reaped: run it under an init, compose's
`init: true`) or when a slot's user is missing.
"""

import argparse
import hmac
import json
import os
import queue
import subprocess
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __package__:
    from . import sandbox
else:  # run as a script: python -I runner/server.py (-I leaves its folder off sys.path)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sandbox

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8001
DEFAULT_SLOTS = 4
MAX_SLOTS = 16
MIN_TOKEN_LENGTH = 16
MAX_BODY_BYTES = 4 * 1024 ** 2
QUEUE_WAIT_SECONDS = 10
SOCKET_TIMEOUT_SECONDS = 30
FIELDS = ('code', 'stdin', 'version', 'header', 'footer')


class ConfigError(Exception):
    """The server can't start with this configuration."""


class RunnerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, token, slots, queue_wait=QUEUE_WAIT_SECONDS):
        super().__init__(address, RunHandler)
        self.token = token.encode('utf-8')
        self.queue_wait = queue_wait
        self.free_slots = queue.Queue()
        for slot in range(slots):
            self.free_slots.put(slot)


class RunHandler(BaseHTTPRequestHandler):
    server_version = 'runner'
    sys_version = ''
    timeout = SOCKET_TIMEOUT_SECONDS

    def do_GET(self):
        if self.path == '/health':
            self.send_json(200, {'status': 'ok'})
        else:
            self.send_json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path != '/run':
            return self.send_json(404, {'error': 'not found'})
        body, error = self.read_body()
        # The body is read (size-capped) even without the token: closing on
        # unread data resets the connection before the client sees the 401.
        if not self.authorized():
            return self.send_json(401, {'error': 'unauthorized'})
        if error:
            return self.send_json(*error)
        fields, problem = parse_run(body)
        if problem:
            return self.send_json(400, {'error': problem})

        try:
            slot = self.server.free_slots.get(timeout=self.server.queue_wait)
        except queue.Empty:
            return self.send_json(503, {'error': 'busy'})
        try:
            result = sandbox.run_python(slot=slot, **fields)
        except subprocess.TimeoutExpired:
            return self.send_json(200, {'returncode': None, 'stdout': '', 'stderr': '',
                                        'timed_out': True})
        except sandbox.RunnerUnavailable as exc:
            self.log_message('unavailable: %s', exc)
            return self.send_json(503, {'error': 'unavailable'})
        except Exception:
            traceback.print_exc()
            return self.send_json(500, {'error': 'internal'})
        finally:
            self.server.free_slots.put(slot)
        self.send_json(200, {'returncode': result.returncode, 'stdout': result.stdout,
                             'stderr': result.stderr, 'timed_out': False})

    def authorized(self):
        scheme, _, given = (self.headers.get('Authorization') or '').partition(' ')
        if scheme != 'Bearer' or not given:
            return False
        return hmac.compare_digest(given.encode('utf-8', 'surrogateescape'), self.server.token)

    def read_body(self):
        """(bytes, None), or (None, (status, payload)) for the error to send."""
        length = self.headers.get('Content-Length')
        if length is None:
            return None, (411, {'error': 'Content-Length required'})
        try:
            length = int(length)
        except ValueError:
            return None, (400, {'error': 'bad Content-Length'})
        if length < 0:
            return None, (400, {'error': 'bad Content-Length'})
        if length > MAX_BODY_BYTES:
            return None, (413, {'error': 'body too large'})
        return self.rfile.read(length), None

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def parse_run(body):
    """({field: str}, None) for a valid /run body, else (None, problem)."""
    try:
        data = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return None, 'body is not JSON'
    if not isinstance(data, dict):
        return None, 'body is not a JSON object'
    fields = {}
    for name in FIELDS:
        value = data.get(name, '')
        if not isinstance(value, str):
            return None, f'{name} must be a string'
        fields[name] = value
    return fields, None


def check_config(token, slots):
    """Raise ConfigError unless the server can run safely like this."""
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f'RUNNER_TOKEN must be set, at least {MIN_TOKEN_LENGTH} characters')
    if not 1 <= slots <= MAX_SLOTS:
        raise ConfigError(f'RUNNER_SLOTS must be 1..{MAX_SLOTS}')
    if sandbox.running_as_root():
        if os.getpid() == 1:
            raise ConfigError('running as PID 1: start it under an init (compose "init: true")')
        for slot in range(slots):
            try:
                sandbox.slot_account(slot)
            except sandbox.RunnerUnavailable as exc:
                raise ConfigError(f'{exc} (RUNNER_SLOTS={slots})')


def slots_from_env(environ):
    try:
        return int(environ.get('RUNNER_SLOTS') or DEFAULT_SLOTS)
    except ValueError:
        raise ConfigError('RUNNER_SLOTS must be a number')


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description='Code runner HTTP server')
    parser.add_argument('--host', default=DEFAULT_HOST)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    token = environ.get('RUNNER_TOKEN', '')
    try:
        slots = slots_from_env(environ)
        check_config(token, slots)
    except ConfigError as exc:
        sys.exit(f'runner: {exc}')
    if sandbox.running_as_root():
        sandbox.lock_shared_dirs()
    server = RunnerHTTPServer((args.host, args.port), token, slots)
    print(f'runner: listening on {args.host}:{args.port}, {slots} slots', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
