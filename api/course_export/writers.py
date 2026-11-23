"""Writers for the native folder (schema 1) and the learner's offline MHTML."""
import json
from copy import deepcopy
from email import policy
from email.generator import BytesGenerator
from email.message import EmailMessage

from django.core.serializers.json import DjangoJSONEncoder
from django.template.loader import render_to_string
from slugify import slugify

from .assets import Assets, ExportTooLarge, visit_rich_text
from .snapshot import STEP_NAMES


def write_json(path, value):
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False, cls=DjangoJSONEncoder)
        stream.write('\n')


def write_folder(target, course, warn, progress, *, asset_limit=None, folder_limit=None):
    target.mkdir(mode=0o700)
    assets = Assets(warn, asset_limit)
    remaining = folder_limit

    def save_json(path, data):
        nonlocal remaining
        write_json(path, data)
        if remaining is not None:
            remaining -= path.stat().st_size
            if remaining < 0:
                raise ExportTooLarge()

    manifest = {key: value for key, value in course.items() if key != 'lessons'}
    manifest.update(format='uchebus-course', schema_version=1, lessons=[])
    if course['cover']:
        manifest['cover_asset'] = assets.resolve(course['cover'], 'Course cover', storage_name=course['cover'])
    lesson_width = max(3, len(str(len(course['lessons']))))
    for number, lesson in enumerate(course['lessons'], 1):
        name = slugify(lesson['title'], max_length=48) or 'lesson'
        directory = target / 'lessons' / f'{number:0{lesson_width}d}-{name}'
        directory.mkdir(parents=True)
        progress(f"Lesson {number}: {lesson['title']} ({len(lesson['steps'])} steps)")
        manifest['lessons'].append((directory / 'lesson.json').relative_to(target).as_posix())
        metadata = {key: value for key, value in lesson.items() if key != 'steps'}
        metadata['steps'] = []
        step_width = max(2, len(str(len(lesson['steps']))))
        for position, step in enumerate(lesson['steps'], 1):
            filename = f"{position:0{step_width}d}_{STEP_NAMES.get(step['type'], 'unknown')}.step"
            metadata['steps'].append(filename)
            where = f"Lesson {lesson['id']}, step {step['id']}"
            if step['type'] in STEP_NAMES and isinstance(step['content'], dict):
                try:
                    visit_rich_text(step['type'], deepcopy(step['content']),
                                    lambda value: assets.html(value, where, offline=False))
                except (TypeError, KeyError, AttributeError):
                    warn(f'{where}: unrecognized rich-text configuration')
            save_json(directory / filename, step)
        save_json(directory / 'lesson.json', metadata)
    manifest['assets'] = assets.references
    manifest['asset_types'] = {}
    for relative, (mime, data) in assets.files.items():
        manifest['asset_types'][relative] = mime
        path = target / relative
        if remaining is not None:
            remaining -= len(data)
            if remaining < 0:
                raise ExportTooLarge()
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
    save_json(target / 'course.json', manifest)


LABELS = {'TEXT': 'Теория', 'QUIZ': 'Тест', 'CODE': 'Задача с кодом', 'FILL': 'Пропуски',
          'SORT': 'Сортировка', 'MATCH': 'Сопоставление', 'TABLE': 'Таблица'}
ARCHIVE_BASE = 'https://uchebus-export.invalid/'


def write_mhtml(target, course, warn, progress, *, asset_limit=None):
    if course['audience'] != 'learner':
        raise ValueError('MHTML requires a learner snapshot')
    assets = Assets(warn, asset_limit)
    cover = course['cover'] and assets.resolve(course['cover'], 'Course cover', storage_name=course['cover'])
    lessons = []
    for number, lesson in enumerate(course['lessons'], 1):
        progress(f"Lesson {number}: {lesson['title']} ({len(lesson['steps'])} steps)")
        blocks = []
        lessons.append({'id': lesson['id'], 'title': lesson['title'], 'blocks': blocks})
        for step in lesson['steps']:
            kind = step['type']
            task = deepcopy(step['content'])
            where = f"Lesson {lesson['id']}, step {step['id']}"
            if task is not None:
                visit_rich_text(kind, task, lambda value: assets.html(value, where, offline=True))
                if kind == 'CODE':
                    task['examples'] = [(test['input'], test['expected']) for test in task['tests']]
                elif kind == 'FILL':
                    task['template'] = task['template'].replace('{{}}', '____')
            blocks.append({'id': step['id'], 'type': kind, 'label': LABELS.get(kind, kind), 'task': task})
    html = render_to_string('exports/course.html', {'course': course, 'cover': cover, 'lessons': lessons})
    archive = EmailMessage(policy=policy.SMTP)
    archive['MIME-Version'] = '1.0'
    archive.make_related()
    archive.set_param('type', 'text/html')
    archive.set_param('start', '<index@uchebus-export.invalid>')
    # Chromium displays the root at the opened file URL, but resolves root
    # fragments against Content-Location. In an archived child document the
    # document URL and link base agree, so a fragment click scrolls in place.
    course_url = ARCHIVE_BASE + 'course.html'
    shell = render_to_string('exports/mhtml_shell.html', {'course': course, 'course_url': course_url})
    root = EmailMessage()
    root.set_content(shell, subtype='html', charset='utf-8', cte='quoted-printable')
    root['Content-ID'] = '<index@uchebus-export.invalid>'
    root['Content-Location'] = ARCHIVE_BASE + 'index.html'
    archive.attach(root)
    document = EmailMessage()
    document.set_content(html, subtype='html', charset='utf-8', cte='quoted-printable')
    document['Content-Location'] = course_url
    archive.attach(document)
    for relative, (mime, data) in assets.files.items():
        part = EmailMessage()
        main, sub = mime.split('/', 1)
        part.set_content(data, maintype=main, subtype=sub, cte='base64')
        part['Content-Location'] = ARCHIVE_BASE + relative
        archive.attach(part)
    with target.open('xb') as stream:
        # Keep ASCII Content-Location URLs literal. Email-style encoded words
        # in a long URL are decoded by mail parsers but not all MHTML readers.
        BytesGenerator(stream, policy=policy.SMTP.clone(max_line_length=998)).flatten(archive)
