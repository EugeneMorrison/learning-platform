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

Hidden code (a CODE block's `header` / `footer`): when either is set, LAUNCHER
runs header → student code → footer as one program in one namespace, under
the same limits and timeout. The student's line numbers stay their own, and
errors never print a source line of the hidden code. Without hidden code the
run is exactly `python main.py`, as before.

Not covered yet: network access; a process that starts its own session
survives the kill (bounded by the process limit).
"""

import json
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
HIDDEN_FILE = 'hidden.json'    # header / footer for LAUNCHER; it deletes the file
HIDDEN_NAME = '<hidden>'       # filename of header / footer in tracebacks

# Runs first, inside the child: lower the limits (an unprivileged process
# can't raise them again; a lower inherited hard limit is kept), then replace
# itself with the student's program (`target`: main.py, or LAUNCHER).
BOOTSTRAP = """\
import os, resource, sys
for name, soft, hard in {limits!r}:
    which = getattr(resource, name)
    current_hard = resource.getrlimit(which)[1]
    if current_hard != resource.RLIM_INFINITY:
        hard = min(hard, current_hard)
    resource.setrlimit(which, (min(soft, hard), hard))
os.execv(sys.executable, [sys.executable] + {flags!r} + {target!r})
"""

# `python -c LAUNCHER`, for a block with hidden code. Reads and deletes
# HIDDEN_FILE, compiles each part on its own (header / footer as HIDDEN_NAME,
# the student's code as main.py: their line 1 is line 1), then runs them in
# the real __main__ namespace, set up as for `python main.py`. On an uncaught
# exception it prints the traceback itself: no launcher frames, and hidden
# frames keep file / line / function but lose their source line. Everything
# lives inside _launch(), the only global it adds, which it removes before
# the parts run. Python 3.10 APIs only (the oldest interpreter offered).
LAUNCHER = """\
def _launch():
    import importlib.machinery, json, os, sys, traceback
    launcher_file = sys._getframe().f_code.co_filename
    with open({hidden_file!r}, encoding='utf-8') as f:
        hidden = json.load(f)
    os.remove({hidden_file!r})
    path = os.path.abspath({code_file!r})
    with open(path, 'rb') as f:
        sources = [(hidden['header'], {hidden_name!r}), (f.read(), path),
                   (hidden['footer'], {hidden_name!r})]
    del hidden
    main = sys.modules['__main__'].__dict__
    try:
        # All parts first: a syntax error anywhere means nothing runs.
        parts = [compile(source, name, 'exec', dont_inherit=True) for source, name in sources]
        del sources
        del main['_launch']
        main.update(__file__=path, __cached__=None,
                    __loader__=importlib.machinery.SourceFileLoader('__main__', path))
        sys.argv[:] = [{code_file!r}]
        for part in parts:
            exec(part, main)
    except SystemExit:
        raise
    except BaseException as exc:
        tb = exc.__traceback__
        while tb is not None and tb.tb_frame.f_code.co_filename == launcher_file:
            tb = tb.tb_next
        report = traceback.TracebackException(type(exc), exc, tb)
        todo, seen = [report], set()
        while todo:
            te = todo.pop()
            if te is None or id(te) in seen:
                continue
            seen.add(id(te))
            te.stack = traceback.StackSummary.from_list([
                traceback.FrameSummary(frame.filename, frame.lineno, frame.name,
                                       lookup_line=False, line='')
                if frame.filename == {hidden_name!r} else frame
                for frame in te.stack])
            if getattr(te, 'filename', None) == {hidden_name!r}:
                te.text = None
            todo += [te.__cause__, te.__context__] + list(getattr(te, 'exceptions', None) or [])
        sys.stderr.write(''.join(report.format()))
        raise SystemExit(1)
_launch()
""".format(hidden_file=HIDDEN_FILE, hidden_name=HIDDEN_NAME, code_file=CODE_FILE)


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


def run_python(code, stdin='', version='', header='', footer=''):
    """
    Run `code` with `stdin`, after `header` and before `footer` (hidden code,
    see LAUNCHER); returns subprocess.CompletedProcess(args, returncode,
    stdout, stderr). Raises subprocess.TimeoutExpired after TIMEOUT_SECONDS
    (wall clock, the whole run), RunnerUnavailable when it can't run safely.
    """
    account = _runner_account()
    python = resolve_python(version)
    base = RUNNER_TMP_BASE if os.path.isdir(RUNNER_TMP_BASE) else None
    workdir = tempfile.mkdtemp(prefix='run-', dir=base)
    try:
        files = {CODE_FILE: code}
        if header or footer:
            files[HIDDEN_FILE] = json.dumps({'header': header, 'footer': footer})
            target = ['-c', LAUNCHER]
        else:
            target = [CODE_FILE]
        for name, text in files.items():
            with open(os.path.join(workdir, name), 'w', encoding='utf-8') as f:
                f.write(text)
        if os.name == 'posix':
            args = [python] + PYTHON_FLAGS + ['-c', BOOTSTRAP.format(
                limits=_limits(account is not None), flags=PYTHON_FLAGS, target=target)]
        else:
            args = [python] + PYTHON_FLAGS + target

        kwargs = {}
        if os.name == 'posix':
            kwargs['start_new_session'] = True
            kwargs['umask'] = 0o077
        if account:
            uid, gid = account
            os.chown(workdir, uid, gid)
            for name in files:
                os.chown(os.path.join(workdir, name), uid, gid)
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
