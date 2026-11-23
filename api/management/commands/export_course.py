import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from slugify import slugify

from api.course_export.snapshot import extract_course
from api.course_export.writers import write_folder, write_mhtml
from api.models import Course


class Command(BaseCommand):
    help = 'Export a course by UUID or slug into a native folder or offline MHTML archive.'

    def add_arguments(self, parser):
        parser.add_argument('course', help='Course UUID or exact slug')
        parser.add_argument('--format', choices=('mhtml', 'folder'), required=True)
        parser.add_argument('--output-dir', required=True, help='Parent directory for the new artifact')
        parser.add_argument('--author-materials', action='store_true',
                            help='Include original exercise configuration and answer keys (folder only)')

    def handle(self, *args, **options):
        private = options['author_materials']
        folder = options['format'] == 'folder'
        if private and not folder:
            raise CommandError('--author-materials is available only with --format folder')
        parent = Path(options['output_dir']).expanduser().resolve()
        reference = Path(settings.BASE_DIR) / 'Uchebus_Stepik_Приложение'
        if parent.is_relative_to(reference.resolve()):
            raise CommandError('Choose an output directory outside the reference materials.')
        if private:
            public_dirs = [settings.MEDIA_ROOT, settings.STATIC_ROOT, *settings.STATICFILES_DIRS]
            if any(p and parent.is_relative_to(Path(p).resolve()) for p in public_dirs):
                raise CommandError('Choose a private output directory outside media and static roots.')
        def warn(message):
            self.stderr.write(self.style.WARNING('Warning: ' + message))

        def progress(message):
            if options['verbosity']:
                self.stdout.write(message)

        try:
            course = extract_course(options['course'], private, warn)
        except Course.DoesNotExist as exc:
            raise CommandError(f"Course not found: {options['course']}") from exc
        stem = (slugify(course['slug'], max_length=48) or 'course') + '-' + course['id']
        name = stem + ('-author' if private else '')
        if not folder:
            name += '.mhtml'
        destination = parent / name
        progress(f"Exporting {course['title']} ({course['id']})")
        try:
            parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(destination):
                raise CommandError(f'Output already exists: {destination}')
            with TemporaryDirectory(prefix='.uchebus-export-', dir=parent) as staging:
                artifact = Path(staging) / name
                if folder:
                    write_folder(artifact, course, warn, progress)
                    artifact.rename(destination)
                else:
                    write_mhtml(artifact, course, warn, progress)
                    # The completed archive becomes visible in one operation;
                    # a concurrent export cannot replace another writer's file.
                    os.link(artifact, destination)
        except OSError as exc:
            raise CommandError(f'Could not write {destination}: {exc}') from exc
        return str(destination)
