"""
Runs one piece of student Python code. Used by runner/server.py inside the
code runner container and, in local development only, in-process by
api/runner.py. Standard library only. Each run:
- gets a fresh directory, its working directory and the only place it may
  write; emptied and removed afterwards;
- gets an empty environment: only PATH and LANG, nothing from the server;
- runs `python -I -B -X utf8`: isolated mode (ignores PYTHON* variables and
  the user site directory), no .pyc files, UTF-8 stdin/stdout;
- on Linux/macOS, gets resource limits (CPU time, address space, file size,
  open files, no core files; processes when it runs as a slot user), set by a
  short bootstrap that then execs the student's interpreter. Not preexec_fn:
  Python documents it as unsafe when threads are running, and the server
  handles requests in threads;
- when the server runs as root (the runner container), runs as the user of
  its concurrency slot: runner0, runner1, ... one per slot, so runs happening
  at the same time never share a user. Before and after the run, everything
  that user still has running is killed (kill(-1) as that user, which also
  catches processes that left the run's session), and the run's directory is
  emptied as that user. As root without the slot's user it refuses to run
  (fails closed);
- runs in its own session, killed as a whole when the run ends or times out;
- writes stdout/stderr to unnamed files the server opened, capped by the file
  size limit, so a flood of output can't fill the server's memory.

Hidden code (a CODE block's `header` / `footer`): when either is set, LAUNCHER
runs header → student code → footer as one program in one namespace, under
the same limits and timeout. The student's line numbers stay their own, and
errors never print a source line of the hidden code. Without hidden code the
run is exactly `python main.py`.

Not covered here: network access (the container's network is internal-only,
see docker-compose.yml). Without a slot user (local development) a process
that starts its own session survives the kill.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

PYTHON_BINARIES = {
    'Python 3.10': '/usr/local/bin/python3.10',
    'Python 3.12': '/usr/local/bin/python3.12',
}

# runner0, runner1, ...: one unprivileged user per concurrency slot (the
# runner image creates them, runner/Dockerfile).
SLOT_USER = 'runner{}'
# Runner container: per-run directories go here (tmpfs, root-owned, 0711).
# Elsewhere the system temp directory is used.
WORK_BASE = '/work'

TIMEOUT_SECONDS = 5          # wall clock
CPU_SECONDS = 5              # soft limit (SIGXCPU); hard limit one second later
MEMORY_BYTES = 256 * 1024 ** 2   # address space
FILE_BYTES = 1024 ** 2       # largest file it may write, stdout/stderr included
OPEN_FILES = 64
PROCESSES = 32               # per slot user
HELPER_SECONDS = 10          # kill / cleanup helpers (they take milliseconds)

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

# `python -c KILL_ALL`, run as a slot user: SIGKILL every process of that user
# (kill(-1) covers every process the caller may signal, i.e. the same user,
# except the caller itself). Only ever run as a slot user: as anyone else it
# would kill all of their processes.
KILL_ALL = """\
import os, signal
try:
    os.kill(-1, signal.SIGKILL)
except OSError:
    pass
"""

# `python -c CLEANUP <dir>`, run as the slot user after the run: KILL_ALL, then
# empty <dir>. Root in the container has no CAP_DAC_OVERRIDE, so it can't
# enter what the student created; the owner can, after making each directory
# accessible again (the student may have chmod-ed them, the run's own
# directory included). Symlinks are removed, never followed.
CLEANUP = KILL_ALL + """\
import shutil, sys
path = sys.argv[1]
def unlock(p):
    try:
        os.chmod(p, 0o700)
    except OSError:
        pass
unlock(path)
for root, dirs, files in os.walk(path):
    for d in dirs:
        if not os.path.islink(os.path.join(root, d)):
            unlock(os.path.join(root, d))
for name in os.listdir(path):
    p = os.path.join(path, name)
    if os.path.isdir(p) and not os.path.islink(p):
        shutil.rmtree(p, ignore_errors=True)
    else:
        try:
            os.unlink(p)
        except OSError:
            pass
"""


class RunnerUnavailable(Exception):
    """Code can't be run safely here (root without the slot's user)."""


def resolve_python(version_str):
    # In the runner image the mapped binaries exist — return them. In local
    # development (Windows/macOS) they don't, so fall back to the interpreter
    # running this code, which is whatever's in the venv.
    path = PYTHON_BINARIES.get(version_str)
    if path and os.path.exists(path):
        return path
    return sys.executable


def running_as_root():
    return os.name == 'posix' and os.geteuid() == 0


def slot_account(slot):
    """(uid, gid) of the slot's user, or None to run as the server's own user
    (not root: local development)."""
    if not running_as_root():
        return None
    if slot is None:
        raise RunnerUnavailable('running as root without a slot')
    import pwd
    name = SLOT_USER.format(slot)
    try:
        entry = pwd.getpwnam(name)
    except KeyError:
        raise RunnerUnavailable(f'running as root without the "{name}" user')
    if entry.pw_uid == 0:
        raise RunnerUnavailable(f'"{name}" is root')
    return entry.pw_uid, entry.pw_gid


def lock_shared_dirs():
    """Runner container, as root: Docker mounts /dev/shm and /dev/mqueue
    world-writable at run time; remove the slot users' write access, so runs
    can write only in their own directory."""
    for path in ('/dev/shm', '/dev/mqueue'):
        try:
            os.chmod(path, os.stat(path).st_mode & ~0o002)
        except OSError:
            pass


def _limits(as_slot_user):
    limits = [
        ('RLIMIT_CPU', CPU_SECONDS, CPU_SECONDS + 1),
        ('RLIMIT_AS', MEMORY_BYTES, MEMORY_BYTES),
        ('RLIMIT_FSIZE', FILE_BYTES, FILE_BYTES),
        ('RLIMIT_NOFILE', OPEN_FILES, OPEN_FILES),
        ('RLIMIT_CORE', 0, 0),
    ]
    # Counted per user: only meaningful for a dedicated slot user (as the
    # developer's own user it would count every process on the machine).
    if as_slot_user:
        limits.append(('RLIMIT_NPROC', PROCESSES, PROCESSES))
    return limits


def _as_slot_user(account, source, *args):
    """Run a helper (KILL_ALL / CLEANUP) as the slot's user."""
    uid, gid = account
    try:
        subprocess.run(
            [sys.executable, '-I', '-S', '-B', '-c', source, *args],
            cwd='/', env=CHILD_ENV, user=uid, group=gid, extra_groups=[],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=HELPER_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pass


def _read(f):
    f.seek(0)
    return f.read().decode('utf-8', errors='replace').replace('\r\n', '\n')


def run_python(code, stdin='', version='', header='', footer='', slot=None):
    """
    Run `code` with `stdin`, after `header` and before `footer` (hidden code,
    see LAUNCHER); returns subprocess.CompletedProcess(args, returncode,
    stdout, stderr). `slot`: the concurrency slot whose user runs the code
    (required as root; the caller makes sure no two runs share a slot).
    Raises subprocess.TimeoutExpired after TIMEOUT_SECONDS (wall clock, the
    whole run), RunnerUnavailable when it can't run safely.
    """
    account = slot_account(slot)
    python = resolve_python(version)
    if account:
        _as_slot_user(account, KILL_ALL)   # nothing left from an earlier run
    base = WORK_BASE if os.path.isdir(WORK_BASE) else None
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
            for name in files:
                os.chown(os.path.join(workdir, name), uid, gid)
            # Popen enters `cwd` BEFORE it switches to the slot user, and
            # root here has no CAP_DAC_OVERRIDE: the directory keeps the
            # server's group with search-only access (0710), so root can
            # enter it but not list it, and other slot users get nothing.
            # chmod first: once chown-ed, root no longer owns it.
            os.chmod(workdir, 0o710)
            os.chown(workdir, uid, os.getegid())
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
        _remove_workdir(workdir, account)


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


def _remove_workdir(workdir, account):
    if account is None:
        shutil.rmtree(workdir, ignore_errors=True)
        return
    # Kill what's left of the slot's user and empty the directory as that
    # user, then remove the empty directory (root owns its parent).
    _as_slot_user(account, CLEANUP, workdir)
    try:
        os.rmdir(workdir)
    except OSError:
        pass
