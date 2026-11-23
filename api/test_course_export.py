import base64
import json
import os
from unittest import skipUnless
from unittest.mock import patch
from email import policy
from email.parser import BytesParser
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from api.models import Block, Course, Lesson, Progress, User


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1kAAAAASUVORK5CYII=')


@override_settings(COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE=False)
class CourseExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        author = User.objects.create_user(username='teacher')
        cls.course = Course.objects.create(title='Строки / Strings', description='About this course', author=author,
                                          price='1234.50', cover='covers/picture.png', tagline='Start here')
        cls.last = Lesson.objects.create(course=cls.course, title='CON / ..', order_index=12)
        cls.first = Lesson.objects.create(course=cls.course, title=cls.last.title, order_index=3, is_preview=True)
        cls.contents = {
            'TEXT': {'html': '<p><em>Theory</em><img src="http://testserver/media/lesson_images/picture.png"></p>'
                             '<img src="https://elsewhere.invalid/out.png" alt="external">'
                             '<img src="/media/absent.png" alt="missing"><script>BAD_SCRIPT()</script>'},
            'CODE': {'prompt': 'Print the result', 'starter_code': 'print("<code>")', 'solution': 'PRIVATE_SOLUTION',
                     'header': 'PRIVATE_HEADER', 'footer': 'PRIVATE_FOOTER', 'output_comparison': 'unordered_lines',
                     'tests': [{'input': 'example', 'expected': 'visible', 'visible': True, 'extra': 'PRIVATE_EXTRA'},
                               {'input': 'PRIVATE_INPUT', 'expected': 'PRIVATE_OUTPUT', 'visible': False}]},
            'QUIZ': {'question': '<b>Choose</b>', 'options': ['one', 'two'], 'multiple_answers': True,
                     'correct_answers': [1], 'shuffle_options': False, 'explanation': 'PRIVATE_EXPLANATION'},
            'FILL': {'prompt': 'Fill here', 'template': 'print({{PRIVATE_FILL}})', 'case_sensitive': True},
            'SORT': {'prompt': 'Sort here', 'items': [{'id': 'z', 'text': 'last'}, {'id': 'a', 'text': 'first'}],
                     'feedback_correct': 'PRIVATE_SORT'},
            'MATCH': {'prompt': 'Match here', 'pairs': [{'left': {'id': 'a', 'text': 'left item'},
                                                       'right': {'id': 'b', 'text': 'right item'}}]},
            'TABLE': {'prompt': 'Table here', 'columns': [{'id': 'c', 'text': 'column'}],
                      'rows': [{'id': 'r', 'text': 'row'}], 'correct_cells': {'r': ['c']}},
        }
        for index, (kind, content) in reversed(list(enumerate(cls.contents.items(), 1))):
            block = Block.objects.create(lesson=cls.first, order_index=index * 2, type=kind, content=content)
        learner = User.objects.create_user(username='PRIVATE_STUDENT')
        Progress.objects.create(student=learner, block=block, lesson=cls.first, answer={'code': 'PRIVATE_SUBMISSION'})
        Block.objects.create(lesson=cls.last, order_index=1, type='FUTURE', content={'raw': 'PRIVATE_FUTURE'})

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        media = self.root / 'media'
        self.enterContext(override_settings(MEDIA_ROOT=media, MEDIA_URL='/media/', ALLOWED_HOSTS=['testserver']))
        for name in ['covers/picture.png', 'lesson_images/picture.png']:
            file = media / name
            file.parent.mkdir(parents=True)
            file.write_bytes(PNG)
        self.err = StringIO()

    def export(self, fmt='folder', *flags, identifier=None):
        return Path(call_command('export_course', identifier or str(self.course.pk), '--format', fmt,
                                 '--output-dir', str(self.root / 'output'), *flags, stdout=StringIO(), stderr=self.err))

    def read_folder(self, root):
        manifest = json.loads((root / 'course.json').read_text('utf-8'))
        lessons = []
        steps = []
        for relative in manifest['lessons']:
            path = root / relative
            lesson = json.loads(path.read_text('utf-8'))
            lessons.append(lesson)
            steps.extend(json.loads((path.parent / name).read_text('utf-8')) for name in lesson['steps'])
        return manifest, lessons, steps

    def test_author_folder_preserves_metadata_order_and_original_configurations(self):
        root = self.export('folder', '--author-materials', identifier=self.course.slug)
        manifest, lessons, steps = self.read_folder(root)
        self.assertEqual((manifest['schema_version'], manifest['audience'], manifest['price']), (1, 'author', '1234.50'))
        self.assertEqual(manifest['id'], str(self.course.pk))
        self.assertEqual([row['id'] for row in lessons], [str(self.first.pk), str(self.last.pk)])
        self.assertEqual([row['order_index'] for row in lessons], [3, 12])
        self.assertTrue(lessons[0]['is_preview'])
        self.assertEqual(lessons[0]['steps'], ['01_text.step', '02_code.step', '03_choice.step', '04_fill-blanks.step',
                                              '05_sorting.step', '06_matching.step', '07_table.step'])
        self.assertEqual([s['order_index'] for s in steps[:-1]], [2, 4, 6, 8, 10, 12, 14])
        self.assertEqual({s['type']: s['content'] for s in steps[:-1]}, self.contents)
        self.assertEqual(steps[-1]['content'], {'raw': 'PRIVATE_FUTURE'})
        self.assertNotIn('PRIVATE_STUDENT', str((manifest, steps)))
        self.assertNotIn('PRIVATE_SUBMISSION', str((manifest, steps)))
        self.assertEqual(len(list((root / 'assets').iterdir())), 1)
        self.assertEqual((root / manifest['cover_asset']).read_bytes(), PNG)
        self.assertEqual(manifest['assets']['http://testserver/media/lesson_images/picture.png'], manifest['cover_asset'])
        self.assertIsNone(manifest['assets']['/media/absent.png'])
        self.assertIn(str(self.last.pk), self.err.getvalue())

    def test_learner_folder_only_keeps_display_fields(self):
        manifest, _, steps = self.read_folder(self.export())
        self.assertEqual(manifest['audience'], 'learner')
        self.assertNotIn('PRIVATE_', str(steps))
        self.assertEqual(steps[1]['content']['tests'], [{'input': 'example', 'expected': 'visible'}])
        self.assertNotIn('correct_answers', steps[2]['content'])
        self.assertEqual(steps[3]['content']['template'], 'print({{}})')
        self.assertEqual(steps[4]['content']['items'][0]['id'], 'a')
        self.assertNotIn('pairs', steps[5]['content'])
        self.assertNotIn('correct_cells', steps[6]['content'])
        self.assertIsNone(steps[-1]['content'])

    def test_mhtml_offline_resources_and_readable_content(self):
        archive = self.export('mhtml').read_bytes()
        msg = BytesParser(policy=policy.default).parsebytes(archive)
        self.assertEqual(msg.get_content_type(), 'multipart/related')
        root, document, image = list(msg.iter_parts())
        self.assertEqual(msg.get_param('start'), root['Content-ID'])
        shell = BeautifulSoup(root.get_content(), 'html.parser')
        self.assertEqual(shell.title.string, self.course.title)
        self.assertEqual(shell.iframe['src'], document['Content-Location'])
        html = document.get_content()
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(soup.title.string, self.course.title)
        for link, lesson in zip(soup.select('nav a'), [self.first, self.last], strict=True):
            anchor = f'lesson-{lesson.pk}'
            self.assertEqual(link['href'], '#' + anchor)
            self.assertEqual(len(soup.find_all(id=anchor)), 1)
            self.assertEqual(soup.find(id=anchor).name, 'h2')
        self.assertEqual(len(soup.select('article')), 8)
        self.assertEqual(soup.em.string, 'Theory')
        for expected in ['About this course', 'print("<code>")', 'example', 'visible', 'Choose', 'print(____)',
                         'Sort here', 'Match here', 'left item', 'Table here', 'column', 'external', 'missing']:
            self.assertIn(expected, soup.get_text())
        self.assertNotIn('PRIVATE_', html)
        self.assertNotIn('BAD_SCRIPT', html)
        self.assertEqual(len(soup.select('img')), 2)
        for img in soup.select('img'):
            self.assertEqual(urljoin(document['Content-Location'], img['src']), image['Content-Location'])
        self.assertEqual(image.get_content_type(), 'image/png')
        self.assertIn(b'Content-Location: ' + image['Content-Location'].encode('ascii') + b'\r\n', archive)
        self.assertEqual(image.get_payload(decode=True), PNG)
        self.assertFalse(soup.select('script, iframe, link, [srcset]'))
        self.assertIn('asset unavailable', self.err.getvalue())

    @skipUnless(os.environ.get('UCHEBUS_TEST_MHTML_BROWSERS'), 'opt-in Chrome and Edge integration test')
    def test_syllabus_click_scrolls_in_the_same_offline_document(self):
        import asyncio
        from playwright.sync_api import sync_playwright

        # Enough space before and after the heading to distinguish a real jump
        # from a click that merely leaves a short document in the viewport.
        for lesson in (self.first, self.last):
            Block.objects.create(lesson=lesson, order_index=100, type='TEXT',
                                 content={'html': '<p>Lesson material</p>' * 80})
        path = self.export('mhtml').rename(self.root / 'Курс offline.mhtml')
        if os.name == 'nt':
            # Daphne selects a Windows event loop without subprocess support.
            # Playwright launches a driver process; restore Daphne's policy after the test.
            self.addCleanup(asyncio.set_event_loop_policy, asyncio.get_event_loop_policy())
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        with sync_playwright() as playwright:
            for channel in os.environ['UCHEBUS_TEST_MHTML_BROWSERS'].split(','):
                with self.subTest(channel=channel):
                    browser = playwright.chromium.launch(channel=channel.strip())
                    try:
                        page = browser.new_page(offline=True, viewport={'width': 900, 'height': 600})
                        page.goto(path.as_uri())
                        opened_url = page.url
                        frame = page.frame_locator('iframe')
                        heading = frame.locator(f'h2[id="lesson-{self.last.pk}"]')
                        top = 'el => el.getBoundingClientRect().top'
                        self.assertGreater(heading.evaluate(top), 600)
                        self.assertGreater(frame.locator('img').first.evaluate('el => el.naturalWidth'), 0)
                        document_requests = []
                        page.on('request', lambda r: document_requests.append(r.url) if r.is_navigation_request() else None)
                        frame.locator('nav a').last.click()
                        self.assertTrue(heading.evaluate('el => document.querySelector(":target") === el'))
                        self.assertAlmostEqual(heading.evaluate(top), 0, delta=2)
                        self.assertEqual(document_requests, [])
                        self.assertEqual(page.url, opened_url)
                        self.assertEqual(page.title(), self.course.title)
                    finally:
                        browser.close()

    def test_command_errors_and_existing_destination(self):
        with self.assertRaisesMessage(CommandError, 'only with --format folder'):
            self.export('mhtml', '--author-materials')
        with self.assertRaisesMessage(CommandError, 'Course not found'):
            self.export(identifier='unknown-course')
        self.export()
        with self.assertRaisesMessage(CommandError, 'already exists'):
            self.export()
        self.assertEqual(len(list((self.root / 'output').iterdir())), 1)

    def test_asset_boundaries_and_static_lookup(self):
        static = self.root / 'static'
        static.mkdir()
        (static / 'example.png').write_bytes(PNG)
        (self.root / 'secret.txt').write_bytes(b'PRIVATE_FILESYSTEM')
        Block.objects.create(lesson=self.last, order_index=2, type='TEXT', content={'html':
            '<img src="/media/%2e%2e/secret.txt"><img src="file:///secret.txt">'
            '<img src="https://other.invalid/media/lesson_images/picture.png"><img src="/static/example.png">'})
        with override_settings(STATICFILES_DIRS=[static]):
            manifest, _, _ = self.read_folder(self.export())
        refs = manifest['assets']
        self.assertEqual(refs['/static/example.png'], manifest['cover_asset'])
        for ref in ('/media/%2e%2e/secret.txt', 'file:///secret.txt', 'https://other.invalid/media/lesson_images/picture.png'):
            self.assertIsNone(refs[ref])

    def test_writer_error_leaves_no_partial_export(self):
        with patch('api.course_export.writers.write_json', side_effect=OSError('disk full')):
            with self.assertRaisesMessage(CommandError, 'disk full'):
                self.export()
        self.assertEqual(list((self.root / 'output').iterdir()), [])
        self.assertTrue(self.export().is_dir())

    def test_author_export_refuses_web_served_destination(self):
        with self.assertRaisesMessage(CommandError, 'private output directory'):
            call_command('export_course', self.course.slug, '--format', 'folder', '--author-materials',
                         '--output-dir', str(self.root / 'media' / 'exports'))

    @override_settings(COURSE_EXPORT_REQUIRE_SEPARATE_DEVICE=True)
    def test_production_command_requires_the_dedicated_output_filesystem(self):
        spool = (self.root / 'spool').resolve()
        spool.mkdir()
        with patch('api.management.commands.export_course.check_capacity', return_value=spool):
            with self.assertRaisesMessage(CommandError, 'dedicated export spool'):
                self.export()
            result = call_command('export_course', self.course.slug, '--format', 'folder',
                                  '--output-dir', str(spool / 'manual'), stdout=StringIO(), stderr=self.err)
            self.assertTrue((Path(result) / 'course.json').is_file())
