"""Internal export subprocess. stdout is the parent's anonymous private file."""
import os
import sys


def main():
    if sys.platform.startswith('linux'):
        import resource
        import signal
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (96 * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (75, 75))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        signal.alarm(90)
        os.nice(10)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
    import django
    django.setup()
    from .build import build
    from .assets import ExportTooLarge
    try:
        build(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == '1', sys.stdout.buffer)
    except (ExportTooLarge, MemoryError):
        raise SystemExit(3)


if __name__ == '__main__':
    main()
