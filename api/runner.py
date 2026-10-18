"""
Runs student Python code for POST /api/run-code/ and /api/run-tests/ — never in
this process. run_python() sends one run to the code runner (runner/server.py,
its own locked-down container: no database, no media, no secrets, no network
but the internal one to this service) and returns its result.

- RUNNER_URL / RUNNER_TOKEN / RUNNER_TIMEOUT: settings (environment). The token
  is required; requests never go through a proxy.
- Only the code, stdin, version and the block's hidden header / footer are
  sent. Expected outputs stay here: the views compare them.
- Results and errors look as when the code ran here: CompletedProcess,
  subprocess.TimeoutExpired after the runner's time limit, RunnerUnavailable
  when there's no runner to ask or it can't run code (→ 503), RunnerBusy when
  every runner slot stays taken (→ 503, try again).

Local development without the runner: with DEBUG on and RUNNER_URL empty, code
runs in-process via runner/sandbox.py. With DEBUG off and RUNNER_URL empty the
endpoints answer 503; the web image has no runner/ folder either, so production
never runs student code in this container.
"""

import json
import subprocess
import urllib.error
import urllib.request

from django.conf import settings

# The runner's wall-clock limit (runner/sandbox.py TIMEOUT_SECONDS): the
# `timeout` of the TimeoutExpired raised when it reports a timed-out run.
TIMEOUT_SECONDS = 5

# No proxies (HTTP_PROXY etc. in the environment): the runner is on the
# internal network only.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class RunnerUnavailable(Exception):
    """Student code can't be run right now (no runner, or it can't run safely)."""


class RunnerBusy(RunnerUnavailable):
    """Every runner slot stayed taken; trying again later may work."""


def run_python(code, stdin='', version='', header='', footer=''):
    """
    Run `code` with `stdin`, after `header` and before `footer` (the block's
    hidden code); returns subprocess.CompletedProcess(args, returncode,
    stdout, stderr). Raises subprocess.TimeoutExpired when the run hit the
    time limit, RunnerBusy / RunnerUnavailable when it couldn't run, TypeError
    for a field that isn't a string.
    """
    fields = {'code': code, 'stdin': stdin, 'version': version, 'header': header, 'footer': footer}
    for name, value in fields.items():
        if not isinstance(value, str):
            raise TypeError(f'{name} must be a string')
    if not settings.RUNNER_URL:
        return _run_in_process(fields)
    if not settings.RUNNER_TOKEN:
        raise RunnerUnavailable('RUNNER_TOKEN is not set')

    request = urllib.request.Request(
        settings.RUNNER_URL, method='POST',
        data=json.dumps(fields).encode('utf-8'),
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {settings.RUNNER_TOKEN}'},
    )
    try:
        with _opener.open(request, timeout=settings.RUNNER_TIMEOUT) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read().decode('utf-8')).get('error')
        except (OSError, ValueError, AttributeError):
            error = None
        if exc.code == 503 and error == 'busy':
            raise RunnerBusy() from exc
        raise RunnerUnavailable(f'runner answered {exc.code} ({error})') from exc
    except (OSError, ValueError) as exc:   # URLError, timeouts, bad JSON
        raise RunnerUnavailable(f'runner not reachable: {exc}') from exc
    return _result(data)


def _result(data):
    """CompletedProcess for the runner's 200 answer (TimeoutExpired for a timed-out run)."""
    if not isinstance(data, dict):
        raise RunnerUnavailable('malformed runner answer')
    if data.get('timed_out') is True:
        raise subprocess.TimeoutExpired('python', TIMEOUT_SECONDS)
    returncode, stdout, stderr = data.get('returncode'), data.get('stdout'), data.get('stderr')
    if not (type(returncode) is int and isinstance(stdout, str) and isinstance(stderr, str)):
        raise RunnerUnavailable('malformed runner answer')
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _run_in_process(fields):
    """Local development only (DEBUG on, no RUNNER_URL): runner/sandbox.py here."""
    if not settings.DEBUG:
        raise RunnerUnavailable('RUNNER_URL is not set')
    try:
        from runner import sandbox
    except ImportError as exc:
        raise RunnerUnavailable('no runner/ folder here') from exc
    try:
        return sandbox.run_python(**fields)
    except sandbox.RunnerUnavailable as exc:
        raise RunnerUnavailable(str(exc)) from exc
