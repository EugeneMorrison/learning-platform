"""
Runs student Python code for POST /api/run-code/ and /api/run-tests/.

INTERIM lockdown until a real sandbox (separate container / nsjail). Each run:
- gets a fresh temporary directory, its working directory and the only place
  it may write; the directory is deleted afterwards;
- gets an empty environment: only PATH and LANG, nothing from the server
  (no SECRET_KEY, nothing from .env);
- runs `python -I -B -X utf8`: isolated mode (ignores PYTHON* variables and
  the user site directory), no .pyc files, UTF-8 stdin/stdout;
- on Linux/macOS, gets resource limits (CPU time, address space, file size,
  open files, no core files; processes when it runs as RUNNER_USER), set by a
  short bootstrap that then execs the student's interpreter. Not preexec_fn:
  Python documents it as unsafe when threads are running, and the server
  runs views in threads;
- when the server runs as root (the Docker image), runs as the unprivileged
  RUNNER_USER; the image keeps /app (code, database, media) out of its reach.
  As root without that user the runner refuses to run (fails closed);
- runs in its own session, killed as a whole when the run ends or times out,
  so forked children don't outlive it;
- writes stdout/stderr to unnamed files the server opened, capped by the file
  size limit, so a flood of output can't fill the server's memory.

Not covered yet: network access; a process that starts its own session
survives the kill (bounded by the process limit).
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

PYTHON_BINARIES = {
    'Python 3.10': '/usr/local/bin/python3.10',
    'Python 3.12': '/usr/local/bin/python3.12',
}

RUNNER_USER = 'runner'
# Docker image: per-run directories go here (root-owned, 0711). Elsewhere the
# system temp directory is used.
RUNNER_TMP_BASE = '/var/lib/runner'

TIMEOUT_SECONDS = 5          # wall clock, as before
CPU_SECONDS = 5              # soft limit (SIGXCPU); hard limit one second later
MEMORY_BYTES = 256 * 1024 ** 2   # address space
FILE_BYTES = 1024 ** 2       # largest file it may write, stdout/stderr included
OPEN_FILES = 64
PROCESSES = 32               # per user: shared by all runs at the same time

# The interpreter flags, for the bootstrap and for the student's code.
PYTHON_FLAGS = ['-I', '-B', '-X', 'utf8']
CHILD_ENV = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}
CODE_FILE = 'main.py'

# Runs first, inside the child: lower the limits (an unprivileged process
# can't raise them again; a lower inherited hard limit is kept), then replace
# itself with the student's program.
BOOTSTRAP = """\
import os, resource, sys
for name, soft, hard in {limits!r}:
    which = getattr(resource, name)
    current_hard = resource.getrlimit(which)[1]
    if current_hard != resource.RLIM_INFINITY:
        hard = min(hard, current_hard)
    resource.setrlimit(which, (min(soft, hard), hard))
os.execv(sys.executable, [sys.executable] + {flags!r} + [{code_file!r}])
"""


class RunnerUnavailable(Exception):
    """The server can't run code safely here (root without RUNNER_USER)."""


def resolve_python(version_str):
    # In Docker (Linux) the mapped binaries exist — return them.
    # In manual setup (Windows/macOS) they don't, so fall back to the
    # interpreter running Django, which is whatever's in the venv.
    path = PYTHON_BINARIES.get(version_str)
    if path and os.path.exists(path):
        return path
    return sys.executable


def _runner_account():
    """(uid, gid) to run as, or None to run as the server's own user."""
    if os.name != 'posix' or os.geteuid() != 0:
        return None
    import pwd
    try:
        entry = pwd.getpwnam(RUNNER_USER)
    except KeyError:
        raise RunnerUnavailable(f'running as root without the "{RUNNER_USER}" user')
    return entry.pw_uid, entry.pw_gid


def _limits(as_runner):
    limits = [
        ('RLIMIT_CPU', CPU_SECONDS, CPU_SECONDS + 1),
        ('RLIMIT_AS', MEMORY_BYTES, MEMORY_BYTES),
        ('RLIMIT_FSIZE', FILE_BYTES, FILE_BYTES),
        ('RLIMIT_NOFILE', OPEN_FILES, OPEN_FILES),
        ('RLIMIT_CORE', 0, 0),
    ]
    # Counted per user: only meaningful for the dedicated runner user (as the
    # developer's own user it would count every process on the machine).
    if as_runner:
        limits.append(('RLIMIT_NPROC', PROCESSES, PROCESSES))
    return limits


def _read(f):
    f.seek(0)
    return f.read().decode('utf-8', errors='replace').replace('\r\n', '\n')


def run_python(code, stdin='', version=''):
    """
    Run `code` with `stdin`; returns subprocess.CompletedProcess(args,
    returncode, stdout, stderr). Raises subprocess.TimeoutExpired after
    TIMEOUT_SECONDS (wall clock), RunnerUnavailable when it can't run safely.
    """
    account = _runner_account()
    python = resolve_python(version)
    base = RUNNER_TMP_BASE if os.path.isdir(RUNNER_TMP_BASE) else None
    workdir = tempfile.mkdtemp(prefix='run-', dir=base)
    try:
        with open(os.path.join(workdir, CODE_FILE), 'w', encoding='utf-8') as f:
            f.write(code)
        if os.name == 'posix':
            args = [python] + PYTHON_FLAGS + ['-c', BOOTSTRAP.format(
                limits=_limits(account is not None), flags=PYTHON_FLAGS, code_file=CODE_FILE)]
        else:
            args = [python] + PYTHON_FLAGS + [CODE_FILE]

        kwargs = {}
        if os.name == 'posix':
            kwargs['start_new_session'] = True
            kwargs['umask'] = 0o077
        if account:
            uid, gid = account
            os.chown(workdir, uid, gid)
            os.chown(os.path.join(workdir, CODE_FILE), uid, gid)
            kwargs.update(user=uid, group=gid, extra_groups=[])

        # Unnamed files the child writes through its stdout/stderr only.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(
                args, cwd=workdir, env=CHILD_ENV,
                stdin=subprocess.PIPE, stdout=out, stderr=err, **kwargs,
            )
            try:
                proc.communicate(input=stdin.encode('utf-8'), timeout=TIMEOUT_SECONDS)
            finally:
                # Also after a normal exit: children it left behind go too.
                _kill(proc)
            # The file size limit stops output at FILE_BYTES. Python ignores
            # SIGXFSZ, so the student's print() gets EFBIG ("OSError: [Errno
            # 27] File too large") rather than the process being killed:
            # detect the cap by the size the output reached.
            stdout_capped = os.fstat(out.fileno()).st_size >= FILE_BYTES
            stderr_capped = os.fstat(err.fileno()).st_size >= FILE_BYTES
            stdout, stderr = _read(out), _read(err)

        returncode = proc.returncode
        limit_mb = FILE_BYTES // 1024 ** 2
        if os.name == 'posix' and (stdout_capped or stderr_capped or returncode == -signal.SIGXFSZ):
            # The traceback is our own limit firing: show the reason instead.
            message = f'Output limit exceeded ({limit_mb} MB)'
            stderr = f'{stderr}\n{message}' if stderr_capped else message
        elif os.name == 'posix' and '[Errno 27]' in stderr:
            # A file the code wrote itself went over the limit.
            stderr += f'\nFile size limit exceeded ({limit_mb} MB)'
        elif os.name == 'posix' and returncode in (-signal.SIGXCPU, -signal.SIGKILL):
            stderr += f'\nTime limit exceeded ({CPU_SECONDS}s CPU)'
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _kill(proc):
    """Kill the child and everything it started in its session."""
    if os.name == 'posix':
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    if _become_subreaper():
        _reap_session(proc.pid)


_subreaper = None


def _become_subreaper():
    """
    Linux: make this server process the "child subreaper" for runs, so the
    orphans of a killed run are re-parented here and can be reaped. Otherwise
    they go to PID 1, which in the container is the Django server itself and
    never reaps them: they'd stay as zombies, counted against the runner
    user's process limit. Standard library only (ctypes → prctl).
    """
    global _subreaper
    if _subreaper is None:
        _subreaper = False
        if sys.platform.startswith('linux'):
            try:
                import ctypes
                PR_SET_CHILD_SUBREAPER = 36
                _subreaper = ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
            except (OSError, AttributeError):
                pass
    return _subreaper


def _session_processes(sid):
    """(pid, ppid) of every process in session `sid`, from /proc."""
    found = []
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        try:
            with open(f'/proc/{entry}/stat', 'rb') as f:
                stat = f.read().decode('ascii', 'replace')
        except OSError:
            continue
        # "pid (comm) state ppid pgrp session ...": comm may contain spaces.
        fields = stat[stat.rfind(')') + 2:].split()
        if len(fields) > 3 and int(fields[3]) == sid:
            found.append((int(entry), int(fields[1])))
    return found


def _reap_session(sid, wait_seconds=2.0):
    """Kill whatever is left of the run's session and reap what was re-parented
    here. Only this session: other runs (other sessions) are never touched."""
    me = os.getpid()
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        remaining = _session_processes(sid)
        if not remaining:
            return
        for pid, ppid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            if ppid == me:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
        time.sleep(0.01)
