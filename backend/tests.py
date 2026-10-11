"""
Tests for the server-rendered public pages (backend/views.py).

Run with: python manage.py test backend
"""

import re
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from api.models import Block, Course, Lesson, User

NBSP = ' '


class PublicPagesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')

    def setUp(self):
        # A request to /en/ leaves English active on the thread, which would make
        # reverse() in the next test build /en/... URLs. Start each test in Russian.
        translation.activate('ru')
        self.addCleanup(translation.deactivate)

    def make_course(self, title, **kwargs):
        kwargs.setdefault('is_published', True)
        return Course.objects.create(title=title, author=self.author, **kwargs)

    def card_titles(self, response):
        return re.findall(r'class="course-card__title">([^<]*)<', response.content.decode())


class LandingCatalogTests(PublicPagesTestCase):
    def test_unpublished_courses_are_not_listed(self):
        self.make_course('Published course')
        self.make_course('Hidden draft', is_published=False)

        response = self.client.get('/')

        self.assertEqual(self.card_titles(response), ['Published course'])

    def test_ordering_is_sort_order_then_title(self):
        self.make_course('Beta', sort_order=1)
        self.make_course('Alpha', sort_order=1)
        self.make_course('Zeta', sort_order=0)

        response = self.client.get('/')

        self.assertEqual(self.card_titles(response), ['Zeta', 'Alpha', 'Beta'])

    def test_free_course_shows_free_label(self):
        self.make_course('Free', price=0)

        response = self.client.get('/')

        self.assertContains(response, 'Бесплатно')
        self.assertNotContains(response, '₽')

    def test_priced_course_shows_formatted_price(self):
        self.make_course('Paid', price=Decimal('1990.00'))

        response = self.client.get('/')

        self.assertContains(response, f'1{NBSP}990{NBSP}₽')
        self.assertNotContains(response, 'Бесплатно')
        self.assertNotContains(response, 'course-price__old')

    def test_non_integer_price_shows_kopecks(self):
        self.make_course('Kopecks', price=Decimal('1990.50'), old_price=Decimal('2490.05'))

        response = self.client.get('/')

        self.assertContains(response, f'1{NBSP}990,50{NBSP}₽')
        self.assertContains(response, f'2{NBSP}490,05{NBSP}₽')

    def test_old_price_shown_only_when_greater_than_price(self):
        self.make_course('Discounted', price=Decimal('1990'), old_price=Decimal('2990'))
        self.make_course('Same price', price=Decimal('1490'), old_price=Decimal('1490'))
        self.make_course('Lower old price', price=Decimal('1290'), old_price=Decimal('990'))

        response = self.client.get('/')

        struck = re.findall(r'</span>([^<]*)</s>', response.content.decode())
        self.assertEqual(struck, [f'2{NBSP}990{NBSP}₽'])

    def test_lesson_count(self):
        course = self.make_course('With lessons')
        for i in range(1, 4):
            Lesson.objects.create(course=course, title=f'Lesson {i}', order_index=i)
        self.make_course('Without lessons')

        response = self.client.get('/')

        self.assertContains(response, 'Уроков: 3')
        self.assertContains(response, 'Уроков: 0')

    def test_empty_state_when_no_published_courses(self):
        self.make_course('Draft only', is_published=False)

        response = self.client.get('/')

        self.assertContains(response, 'Курсы скоро появятся')
        self.assertNotContains(response, 'catalog__list')

    def test_english_hero_headline(self):
        self.make_course('Основы', price=0)

        response = self.client.get('/en/')

        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, 'Learn Python step by step')
        self.assertContains(response, 'Lessons: 0')
        self.assertContains(response, 'Free')
        # Database content stays as entered (no model translations yet).
        self.assertContains(response, 'Основы')

    def test_catalog_query_count_does_not_grow_with_courses(self):
        def add_course(n):
            course = self.make_course(f'Course {n}')
            Lesson.objects.create(course=course, title='Lesson', order_index=1)

        # 3 = courses + author profile + published reviews (the header link reuses them).
        add_course(1)
        with self.assertNumQueries(3):
            self.client.get('/')

        for n in range(2, 7):
            add_course(n)
        with self.assertNumQueries(3):
            response = self.client.get('/')
        self.assertEqual(len(self.card_titles(response)), 6)


class CourseDetailTests(PublicPagesTestCase):
    def make_lesson(self, course, title, order_index, block_types=()):
        lesson = Lesson.objects.create(course=course, title=title, order_index=order_index)
        for i, block_type in enumerate(block_types, start=1):
            Block.objects.create(lesson=lesson, type=block_type, order_index=i, content={})
        return lesson

    def lesson_titles(self, response):
        return re.findall(r'class="syllabus__title">([^<]*)<', response.content.decode())

    def test_published_course_returns_200_under_ru_and_en(self):
        course = self.make_course('Python basics')

        for prefix, lang in [('', 'ru'), ('/en', 'en')]:
            response = self.client.get(f'{prefix}/course/{course.slug}/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, f'<html lang="{lang}">')
            self.assertContains(response, '<title>Python basics — ')

    def test_unpublished_or_missing_course_returns_404_under_ru_and_en(self):
        course = self.make_course('Draft', is_published=False)

        for prefix in ['', '/en']:
            for slug in [course.slug, 'no-such-course']:
                response = self.client.get(f'{prefix}/course/{slug}/')
                self.assertEqual(response.status_code, 404, f'{prefix}/course/{slug}/')

    def test_lessons_in_order_index_order(self):
        course = self.make_course('Ordered')
        self.make_lesson(course, 'Third', 30)
        self.make_lesson(course, 'First', 10)
        self.make_lesson(course, 'Second', 20)

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertEqual(self.lesson_titles(response), ['First', 'Second', 'Third'])
        self.assertContains(response, 'class="step-badge">03<')

    def test_block_counts_per_type_and_zero_types_hidden(self):
        course = self.make_course('Counts')
        self.make_lesson(course, 'Mixed', 1, ['TEXT', 'TEXT', 'QUIZ', 'CODE', 'CODE', 'CODE'])
        self.make_lesson(course, 'Theory only', 2, ['TEXT'])

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))
        html = response.content.decode()
        mixed = html[html.index('>Mixed<'):html.index('>Theory only<')]
        theory = html[html.index('>Theory only<'):html.index('</ol>')]

        self.assertIn('Теория: 2', mixed)
        self.assertIn('Тесты: 1', mixed)
        self.assertIn('Задачи: 3', mixed)
        self.assertNotIn('Пропуски:', mixed)
        self.assertIn('Теория: 1', theory)
        self.assertNotIn('Тесты:', theory)
        self.assertNotIn('Задачи:', theory)
        # Summary line: totals across lessons.
        summary = html[html.index('syllabus-summary'):html.index('syllabus-lock-note')]
        for label in ['Уроков: 2', 'Теория: 3', 'Тесты: 1', 'Задачи: 3']:
            self.assertIn(label, summary)
        self.assertNotIn('Пропуски:', summary)

    def test_block_content_never_reaches_the_page(self):
        marker = 'SECRET-MARKER-7f3c'
        course = self.make_course('Secrets')
        lesson = self.make_lesson(course, 'Lesson', 1)
        Block.objects.create(lesson=lesson, type='CODE', order_index=1, content={
            'prompt': f'{marker}-prompt',
            'starter_code': f'{marker}-starter',
            'solution': f'{marker}-solution',
            'tests': [{'input': f'{marker}-in', 'expected': f'{marker}-out'}],
        })
        Block.objects.create(lesson=lesson, type='QUIZ', order_index=2, content={
            'question': f'{marker}-q', 'options': [f'{marker}-a'], 'correct_answer': 0,
        })
        Block.objects.create(lesson=lesson, type='TEXT', order_index=3,
                             content={'html': f'<p>{marker}-text</p>'})

        for url in [f'/course/{course.slug}/', f'/en/course/{course.slug}/']:
            response = self.client.get(url)
            self.assertNotContains(response, marker)
            # The context itself holds only titles and integer counts.
            for row in response.context['lessons']:
                self.assertEqual(
                    set(row), {'title', 'text_count', 'quiz_count', 'code_count', 'fill_count'})

    def test_description_is_escaped(self):
        course = self.make_course(
            'Escaped', description='Intro <script>alert("x")</script>\n\nSecond paragraph')

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertNotContains(response, '<script>alert')
        self.assertContains(response, '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;')
        self.assertContains(response, '<p>Second paragraph</p>')

    def test_empty_description_section_is_omitted(self):
        course = self.make_course('No description')

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertNotContains(response, 'course-description')

    def test_free_course_cta_goes_to_react_enrol_route(self):
        course = self.make_course('Free', price=0, stepik_id=111)

        ru = self.client.get(f'/course/{course.slug}/')
        en = self.client.get(f'/en/course/{course.slug}/')

        # Same href in both languages: /enroll/ is a React route, not i18n-prefixed.
        self.assertContains(ru, f'href="/enroll/{course.id}/">Начать бесплатно</a>')
        self.assertContains(en, f'href="/enroll/{course.id}/">Start for free</a>')
        self.assertNotContains(ru, 'stepik.org')

    def test_enrol_route_is_served_by_the_react_app(self):
        from django.urls import resolve
        from backend.urls import spa_view

        self.assertIs(resolve('/enroll/3fa85f64-5717-4562-b3fc-2c963f66afa6/').func, spa_view)

    def test_priced_course_with_stepik_id_links_to_stepik(self):
        course = self.make_course('On Stepik', price=Decimal('1990'), stepik_id=123456)

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertContains(response, 'href="https://stepik.org/course/123456/promo"')
        self.assertContains(response, 'Доступен на Stepik')
        self.assertContains(response, f'1{NBSP}990{NBSP}₽')
        self.assertNotContains(response, 'Начать бесплатно')

    def test_priced_course_without_stepik_id_shows_coming_soon(self):
        course = self.make_course(
            'Coming', price=Decimal('1990'), old_price=Decimal('2990'))

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertContains(response, 'class="course-offer__note">Скоро на этой платформе</p>')
        self.assertNotContains(response, 'stepik.org')
        self.assertNotContains(response, 'Начать бесплатно')
        struck = re.findall(r'</span>([^<]*)</s>', response.content.decode())
        self.assertEqual(struck, [f'2{NBSP}990{NBSP}₽'])

    def test_query_count_does_not_grow_with_lessons(self):
        course = self.make_course('Queries')
        url = reverse('course_detail', kwargs={'slug': course.slug})
        self.make_lesson(course, 'Lesson 1', 1, ['TEXT', 'QUIZ', 'CODE', 'FILL'])

        # 3 = course + syllabus + the header's "reviews published?" EXISTS check.
        with self.assertNumQueries(3):
            self.client.get(url)

        for n in range(2, 7):
            self.make_lesson(course, f'Lesson {n}', n, ['TEXT', 'QUIZ', 'CODE', 'FILL'])
        with self.assertNumQueries(3):
            response = self.client.get(url)
        self.assertEqual(len(self.lesson_titles(response)), 6)

    def test_empty_syllabus_state(self):
        course = self.make_course('No lessons yet')

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertContains(response, 'Программа скоро появится')
        self.assertNotContains(response, 'class="syllabus"')

    def test_ru_and_en_labels(self):
        course = self.make_course('Labels')
        self.make_lesson(course, 'All types', 1, ['TEXT', 'QUIZ', 'CODE', 'FILL'])

        ru = self.client.get(f'/course/{course.slug}/')
        en = self.client.get(f'/en/course/{course.slug}/')

        for label in ['Программа курса', 'Уроков: 1', 'Теория: 1', 'Тесты: 1', 'Задачи: 1',
                      'Пропуски: 1', 'Уроки откроются после записи на курс.', 'Все курсы',
                      'Начать бесплатно']:
            self.assertContains(ru, label)
        for label in ['Course syllabus', 'Lessons: 1', 'Theory: 1', 'Quizzes: 1', 'Exercises: 1',
                      'Fill-ins: 1', 'Lessons unlock after you enroll in the course.',
                      'All courses', 'Start for free']:
            self.assertContains(en, label)
        self.assertContains(en, 'href="/en/#catalog">← All courses<')

    def test_header_courses_link_returns_to_landing_catalog(self):
        course = self.make_course('Python basics')

        ru = self.client.get(f'/course/{course.slug}/')
        en = self.client.get(f'/en/course/{course.slug}/')

        self.assertContains(ru, 'class="site-nav__link" href="/#catalog">Курсы<')
        self.assertContains(en, 'class="site-nav__link" href="/en/#catalog">Courses<')

    def test_landing_cards_link_to_course_page(self):
        course = self.make_course('Linked')

        response = self.client.get('/')

        self.assertContains(response, f'href="/course/{course.slug}/"')


class HeaderAuthLinkTests(PublicPagesTestCase):
    """Login links (header "Войти", hero "Войти в аккаунт") are server-rendered; one
    inline script in base.html swaps every link carrying data-account-* for
    "Мой кабинет" when the React app's token is in localStorage (cosmetic only)."""

    # (link id, url, login label, account label)
    LINKS = [
        ('header-auth-link', '/', 'Войти', 'Мой кабинет'),
        ('header-auth-link', '/en/', 'Log in', 'My account'),
        ('hero-auth-link', '/', 'Войти в аккаунт', 'Мой кабинет'),
        ('hero-auth-link', '/en/', 'Log in to your account', 'My account'),
    ]

    def test_both_labels_rendered_for_the_script(self):
        for link_id, url, login_label, account_label in self.LINKS:
            with self.subTest(link=link_id, url=url):
                html = self.client.get(url).content.decode()
                link = re.search(rf'<a [^>]*id="{link_id}"[^>]*>([^<]*)</a>', html)

                self.assertIsNotNone(link)
                # Without JS (or with storage blocked) visitors get the login link.
                self.assertEqual(link.group(1), login_label)
                self.assertIn('href="/login/"', link.group(0))
                # The script's replacement, translated by Django.
                self.assertIn('data-account-href="/dashboard/"', link.group(0))
                self.assertIn(f'data-account-label="{account_label}"', link.group(0))

    def login_script(self, html):
        scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
        matching = [s for s in scripts if 'access_token' in s]
        self.assertEqual(len(matching), 1, 'exactly one login-aware script')
        return matching[0]

    def test_one_script_handles_every_login_link_safely(self):
        script = self.login_script(self.client.get('/').content.decode())

        # Same key as frontend/src/api.js; storage access guarded by try/catch.
        self.assertIn("localStorage.getItem('access_token')", script)
        self.assertIn('try {', script)
        self.assertIn('catch (e)', script)
        # Generic: every link with data-account-href, not one hard-coded id.
        self.assertIn("querySelectorAll('a[data-account-href]')", script)

    def test_script_runs_after_the_links(self):
        # At the end of <body>, so the header and the hero both exist when it runs.
        html = self.client.get('/').content.decode()
        script_at = html.index(self.login_script(html))
        self.assertLess(html.index('id="header-auth-link"'), script_at)
        self.assertLess(html.index('id="hero-auth-link"'), script_at)

    def test_course_page_has_the_same_header_link(self):
        course = self.make_course('Header')
        response = self.client.get(f'/course/{course.slug}/')
        self.assertContains(response, 'id="header-auth-link"')
        self.assertContains(response, 'data-account-label="Мой кабинет"')

    def test_expired_token_is_rejected_by_the_dashboard_check(self):
        # /dashboard/ loads /api/auth/me/; a 401 there (after a failed refresh in
        # frontend/src/api.js) sends the user to /login/.
        from datetime import timedelta
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken.for_user(self.author)
        token.set_exp(lifetime=timedelta(seconds=-1))

        expired = self.client.get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {token}')
        anonymous = self.client.get('/api/auth/me/')

        self.assertEqual(expired.status_code, 401)
        self.assertEqual(anonymous.status_code, 401)


class HeroCodeCardTests(PublicPagesTestCase):
    """Hero shows Python through a decorative code card (no logos), translated."""

    CASES = [
        ('/', 'ru', ['>Учитесь Python шаг за шагом<', '# Урок 1: функции',
                     'f"Привет, {name}!"', '"Мир"', 'Вывод', 'Привет, Мир!',
                     '✓ Все тесты пройдены (3/3)',
                     'Пример задачи: функция на Python возвращает приветствие']),
        ('/en/', 'en', ['>Learn Python step by step<', '# Lesson 1: functions',
                        'f"Hello, {name}!"', '"World"', 'Output', 'Hello, World!',
                        '✓ All tests passed (3/3)',
                        'Example task: a Python function returns a greeting']),
    ]

    def test_card_renders_translated(self):
        for url, lang, expected in self.CASES:
            html = self.client.get(url).content.decode()
            with self.subTest(lang=lang):
                self.assertIn('lesson_01.py', html)
                for text in expected:
                    self.assertIn(text, html)

    def test_card_is_decorative_with_a_text_alternative(self):
        html = self.client.get('/').content.decode()
        card = re.search(r'<div class="code-card"([^>]*)>', html)
        self.assertIsNotNone(card)
        self.assertIn('aria-hidden="true"', card.group(1))
        # The sentence for screen readers sits outside the hidden card.
        sentence_at = html.index('<p class="visually-hidden">Пример задачи')
        self.assertLess(sentence_at, card.start())
        # Old decorative path is gone from the hero; cards keep their step badges.
        self.assertNotIn('hero-path', html)

    def test_no_remote_font_hosts(self):
        from django.contrib.staticfiles import finders

        for url in ['/', '/en/']:
            html = self.client.get(url).content.decode()
            for host in ['fonts.googleapis.com', 'fonts.gstatic.com']:
                self.assertNotIn(host, html, url)
            # Every stylesheet / script the page loads is our own (/static/...).
            for ref in re.findall(r'<(?:link|script)[^>]+(?:href|src)="([^"]+)"', html):
                self.assertTrue(ref.startswith('/'), f'{url}: {ref}')

        css = open(finders.find('public/css/fonts.css'), encoding='utf-8').read()
        self.assertNotIn('http', css)
        self.assertIn('url("../fonts/JetBrainsMono-Regular.woff2")', css)
        # The font ships with its licence alongside.
        self.assertIsNotNone(finders.find('public/fonts/JetBrainsMono-Regular.woff2'))
        self.assertIsNotNone(finders.find('public/fonts/JetBrainsMono-OFL.txt'))


class ProductionStaticFilesTests(TestCase):
    """DEBUG=False with the production storage: the landing page renders and links
    content-hashed stylesheets (collected into a temporary STATIC_ROOT)."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from django.core.management import call_command
        from django.test.utils import override_settings

        cls.static_root = tempfile.mkdtemp()
        cls.prod = override_settings(
            DEBUG=False,
            STATIC_ROOT=cls.static_root,
            STORAGES={
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
            },
        )
        cls.prod.enable()
        call_command('collectstatic', interactive=False, verbosity=0)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        import shutil

        super().tearDownClass()
        cls.prod.disable()
        shutil.rmtree(cls.static_root, ignore_errors=True)

    def test_landing_page_links_hashed_stylesheets(self):
        import os

        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        landing = re.search(r'href="/static/(public/css/landing\.[0-9a-f]{12}\.css)"', html)
        self.assertIsNotNone(landing, 'landing.css is not linked by its hashed name')
        self.assertTrue(os.path.exists(os.path.join(self.static_root, landing.group(1))))
        # No unhashed public stylesheet left in the page.
        self.assertNotRegex(html, r'href="/static/public/css/[a-z]+\.css"')


class AuthorAndReviewsSectionTests(PublicPagesTestCase):
    """"Об авторе" and "Отзывы" come from the admin (AuthorProfile, Review); each is
    hidden while empty, and /en/ falls back to the Russian text."""

    def make_profile(self, **kwargs):
        from api.models import AuthorProfile
        defaults = dict(name='Людмила', bio_ru='Преподаю Python.', photo='author/me.jpg')
        defaults.update(kwargs)
        return AuthorProfile.objects.create(**defaults)

    def make_review(self, **kwargs):
        from api.models import Review
        defaults = dict(student_name='Анна', text_ru='Отличный курс!', is_published=True)
        defaults.update(kwargs)
        return Review.objects.create(**defaults)

    def test_both_sections_and_nav_link_hidden_when_empty(self):
        self.make_review(student_name='Черновик', is_published=False)  # unpublished only
        course = self.make_course('Course')

        for url in ['/', '/en/', f'/course/{course.slug}/']:
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                self.assertNotIn('id="author"', html)
                self.assertNotIn('id="reviews"', html)
                self.assertNotIn('#reviews"', html)  # header link hidden
                self.assertNotIn('Черновик', html)

    def test_sections_shown_when_filled(self):
        course = self.make_course('Python Basics')
        draft_course = self.make_course('Secret draft', is_published=False)
        self.make_profile(stepik_url='https://stepik.org/users/1')
        self.make_review(student_name='Второй', order=2, source='Stepik',
                         source_url='https://stepik.org/review/1', course=course)
        self.make_review(student_name='Первый', order=1, course=draft_course)
        self.make_review(student_name='Скрытый', is_published=False)

        html = self.client.get('/').content.decode()

        self.assertIn('id="author"', html)
        self.assertIn('Об авторе', html)
        self.assertIn('Людмила', html)
        self.assertIn('<p>Преподаю Python.</p>', html)
        self.assertIn('src="/media/author/me.jpg"', html)
        self.assertIn('href="https://stepik.org/users/1"', html)

        self.assertIn('id="reviews"', html)
        self.assertLess(html.index('Первый'), html.index('Второй'))  # order
        self.assertNotIn('Скрытый', html)
        self.assertIn('href="https://stepik.org/review/1"', html)
        self.assertIn('class="review-card__course">Python Basics<', html)
        self.assertNotIn('Secret draft', html)  # unpublished course title not shown

        # Header link to the reviews section, on the landing and on other pages.
        self.assertIn('href="/#reviews">Отзывы<', html)
        course_html = self.client.get(f'/course/{course.slug}/').content.decode()
        self.assertIn('href="/#reviews">Отзывы<', course_html)

    def test_author_section_without_photo_or_bio(self):
        self.make_profile(photo='', bio_ru='')
        html = self.client.get('/').content.decode()
        self.assertIn('id="author"', html)
        self.assertNotIn('author__photo', html)
        self.assertNotIn('author__bio', html)

    def test_english_falls_back_to_russian(self):
        self.make_profile(bio_en='')
        self.make_review(student_name='Без перевода', text_ru='Только по-русски', text_en='')
        self.make_review(student_name='С переводом', text_ru='По-русски', text_en='In English')

        html = self.client.get('/en/').content.decode()

        self.assertIn('About the author', html)
        self.assertIn('<p>Преподаю Python.</p>', html)  # bio_en empty → Russian
        self.assertIn('Только по-русски', html)        # text_en empty → Russian
        self.assertIn('In English', html)
        self.assertNotIn('<p>По-русски</p>', html)
        self.assertIn('href="/en/#reviews">Reviews<', html)

    def test_english_text_used_when_filled(self):
        self.make_profile(bio_en='I teach Python.')
        html = self.client.get('/en/').content.decode()
        self.assertIn('<p>I teach Python.</p>', html)
        self.assertNotIn('Преподаю Python.', html)

    def test_bio_and_review_text_are_escaped(self):
        self.make_profile(bio_ru='<script>alert(1)</script>')
        self.make_review(text_ru='<b>bold</b>')
        html = self.client.get('/').content.decode()
        self.assertNotIn('<script>alert(1)', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('&lt;b&gt;bold&lt;/b&gt;', html)

    def test_admin_allows_a_single_author_profile(self):
        from django.contrib.admin.sites import site
        from django.test import RequestFactory
        from api.models import AuthorProfile

        admin_user = User.objects.create_superuser('boss', 'b@example.com', 'x')
        request = RequestFactory().get('/admin/')
        request.user = admin_user
        model_admin = site._registry[AuthorProfile]

        self.assertTrue(model_admin.has_add_permission(request))
        self.make_profile()
        self.assertFalse(model_admin.has_add_permission(request))

    def test_paragraphs_kept_and_photo_has_alt_text(self):
        self.make_profile(name='Людмила', bio_ru='Первый абзац.\n\nВторой абзац.')
        self.make_review(text_ru='Начало отзыва.\n\nПродолжение.')

        html = self.client.get('/').content.decode()

        # linebreaks: escaped first, blank lines become separate paragraphs.
        self.assertIn('<p>Первый абзац.</p>\n\n<p>Второй абзац.</p>', html)
        self.assertIn('<p>Начало отзыва.</p>\n\n<p>Продолжение.</p>', html)
        self.assertRegex(html, r'<img class="author__photo" src="/media/author/me\.jpg" alt="Людмила"')


class AuthorNameAndBioFormattingTests(PublicPagesTestCase):
    """name_en with fallback to name; bio paragraphs and safe subheadings."""

    # Reuse the helper without re-running AuthorAndReviewsSectionTests' tests.
    make_profile = AuthorAndReviewsSectionTests.make_profile

    def name_in_page(self, url):
        html = self.client.get(url).content.decode()
        name = re.search(r'<p class="author__name">([^<]*)</p>', html).group(1)
        alt = re.search(r'<img class="author__photo"[^>]* alt="([^"]*)"', html).group(1)
        return name, alt

    def test_english_name_used_on_en(self):
        self.make_profile(name='Людмила Иванова', name_en='Lyudmila Ivanova')
        self.assertEqual(self.name_in_page('/'), ('Людмила Иванова', 'Людмила Иванова'))
        self.assertEqual(self.name_in_page('/en/'), ('Lyudmila Ivanova', 'Lyudmila Ivanova'))

    def test_english_name_falls_back_to_russian(self):
        self.make_profile(name='Людмила Иванова', name_en='')
        self.assertEqual(self.name_in_page('/en/'), ('Людмила Иванова', 'Людмила Иванова'))

    def test_whitespace_only_english_name_falls_back(self):
        self.make_profile(name='Людмила', name_en='   ')
        self.assertEqual(self.name_in_page('/en/')[0], 'Людмила')

    def test_short_standalone_line_becomes_subheading(self):
        self.make_profile(bio_ru='Опыт\n\nПреподаю десять лет.\nПишу курсы.\n\nЧему я учу\n\nPython с нуля.')
        html = self.client.get('/').content.decode()
        self.assertIn('<h3 class="author__subheading">Опыт</h3>', html)
        self.assertIn('<p>Преподаю десять лет.<br>Пишу курсы.</p>', html)
        self.assertIn('<h3 class="author__subheading">Чему я учу</h3>', html)
        self.assertIn('<p>Python с нуля.</p>', html)

    def test_sentences_and_last_line_stay_paragraphs(self):
        # Ends with punctuation, too long, multi-line, or nothing after it → paragraph.
        long_line = 'Слово ' * 15
        self.make_profile(bio_ru=f'Привет!\n\n{long_line.strip()}\n\nДве\nстроки\n\nПоследняя строка')
        html = self.client.get('/').content.decode()
        self.assertNotIn('author__subheading', html)
        self.assertIn('<p>Привет!</p>', html)
        self.assertIn('<p>Последняя строка</p>', html)

    def test_subheadings_never_render_author_html(self):
        self.make_profile(bio_ru='<b onclick=x>Опыт</b>\n\n<script>alert(1)</script> text.')
        html = self.client.get('/').content.decode()
        self.assertIn('<h3 class="author__subheading">&lt;b onclick=x&gt;Опыт&lt;/b&gt;</h3>', html)
        self.assertNotIn('<script>alert(1)', html)
        self.assertNotIn('<b onclick', html)

    def test_admin_form_shows_name_en_after_name(self):
        from django.contrib.admin.sites import site
        from api.models import AuthorProfile

        fields = site._registry[AuthorProfile].fields
        self.assertEqual(fields[:2], ['name', 'name_en'])
