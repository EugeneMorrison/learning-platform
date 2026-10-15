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
        self.assertContains(response, "I'm Lyudmila Kolesnikova")
        self.assertContains(response, 'Lessons: 0')
        self.assertContains(response, 'Free')
        # Database content stays as entered (no model translations yet).
        self.assertContains(response, 'Основы')

    def test_catalog_query_count_does_not_grow_with_courses(self):
        def add_course(n):
            course = self.make_course(f'Course {n}')
            Lesson.objects.create(course=course, title='Lesson', order_index=1)

        # 2 = courses + published reviews (the header link reuses them).
        add_course(1)
        with self.assertNumQueries(2):
            self.client.get('/')

        for n in range(2, 7):
            add_course(n)
        with self.assertNumQueries(2):
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


class HeroTests(PublicPagesTestCase):
    """Hero: text + a two-layer picture (the violet illustration behind the
    author's cut-out), WebP with PNG fallbacks, loaded eagerly, alt translated."""

    CASES = [('/', 'ru', 'Людмила Колесникова'), ('/en/', 'en', 'Lyudmila Kolesnikova')]

    def hero_html(self, url):
        html = self.client.get(url).content.decode()
        return re.search(r'<section class="hero".*?</section>', html, re.S).group(0)

    # (picture class, WebP srcset entries, PNG fallback, width/height attributes)
    LAYERS = [
        ('hero__bg', ['hero-bg-768.webp 768w', 'hero-bg-1536.webp 1536w'], 'hero-bg.png', (1536, 1024)),
        ('hero__author', ['hero-author-432.webp 432w', 'hero-author-864.webp 864w'], 'hero-author.png', (864, 1120)),
    ]

    def layer(self, hero, css_class):
        return re.search(rf'<picture class="{css_class}">.*?</picture>', hero, re.S).group(0)

    def test_two_layers_with_webp_sources_and_png_fallback(self):
        for url, lang, alt in self.CASES:
            hero = self.hero_html(url)
            # Back layer first in the markup; the author paints on top of it.
            self.assertLess(hero.index('class="hero__bg"'), hero.index('class="hero__author"'))
            for css_class, srcset, png, (width, height) in self.LAYERS:
                with self.subTest(lang=lang, layer=css_class):
                    picture = self.layer(hero, css_class)
                    source = re.search(r'<source type="image/webp"[^>]*>', picture).group(0)
                    for entry in srcset:
                        self.assertIn(f'public/img/{entry}', source)
                    img = re.search(r'<img[^>]*>', picture).group(0)
                    self.assertIn(f'public/img/{png}"', img)
                    self.assertIn(f'width="{width}" height="{height}"', img)
                    self.assertNotIn('loading=', img)  # above the fold: never lazy

    def test_background_is_decorative_and_author_has_alt(self):
        for url, lang, alt in self.CASES:
            hero = self.hero_html(url)
            with self.subTest(lang=lang):
                bg = re.search(r'<img[^>]*>', self.layer(hero, 'hero__bg')).group(0)
                self.assertIn('alt=""', bg)
                self.assertIn('aria-hidden="true"', bg)
                author = re.search(r'<img[^>]*>', self.layer(hero, 'hero__author')).group(0)
                self.assertIn(f'alt="{alt}"', author)
                self.assertNotIn('aria-hidden', author)
                # The flattened picture is no longer used.
                self.assertNotIn('public/img/hero.png', hero)
                self.assertNotIn('public/img/hero-896.webp', hero)

    def test_files_exist_and_match_the_size_attributes(self):
        from django.contrib.staticfiles import finders
        from PIL import Image

        for _, srcset, png, (width, height) in self.LAYERS:
            for name in [png] + [entry.split()[0] for entry in srcset]:
                path = finders.find(f'public/img/{name}')
                self.assertIsNotNone(path, name)
                with Image.open(path) as im:
                    self.assertEqual(im.mode, 'RGBA', name)  # transparent layers
                    # Same aspect ratio as the width/height attributes (no layout shift).
                    self.assertAlmostEqual(im.width / im.height, width / height, places=2, msg=name)

    def test_code_card_and_cat_are_gone(self):
        hero = self.hero_html('/')
        for old in ['code-card', 'lesson_01.py', 'hero__cat', 'cat-desk']:
            self.assertNotIn(old, hero)
        # The cat artwork stays in static files for later use.
        from django.contrib.staticfiles import finders
        self.assertIsNotNone(finders.find('public/img/cat-desk-800.webp'))

    TEXTS = {
        '/': ['<p class="hero__eyebrow">Привет!</p>',
              '<h1 id="hero-title" class="hero__title">Я Людмила Колесникова</h1>',
              '<p>Автор образовательного проекта учиЛКа.</p>',
              '<p>Уже более 10 лет я преподаю, создаю образовательные курсы и руковожу проектами.</p>',
              '<p>Здесь я делюсь своим опытом и знаниями: от программирования и создания игр '
              'до управления людьми и командами.</p>',
              '<p>Люблю объяснять сложное простыми словами и уверена, что ошибки — лучшие учителя, '
              'а не повод сдаваться!</p>',
              '>Смотреть курсы<', 'data-account-label="Мой кабинет"'],
        '/en/': ['<p class="hero__eyebrow">Hi!</p>',
                 '<h1 id="hero-title" class="hero__title">I\'m Lyudmila Kolesnikova</h1>',
                 '<p>Author of the educational project uchiLKa.</p>',
                 '<p>For more than 10 years I have been teaching, creating educational courses '
                 'and leading projects.</p>',
                 '<p>Here I share my experience and knowledge: from programming and game development '
                 'to managing people and teams.</p>',
                 '<p>I love explaining complex things in simple words, and I believe that mistakes '
                 'are the best teachers, not a reason to give up!</p>',
                 '>Browse courses<', 'data-account-label="My account"'],
    }

    def test_author_texts_in_ru_and_en(self):
        for url, texts in self.TEXTS.items():
            hero = self.hero_html(url)
            with self.subTest(url=url):
                for text in texts:
                    self.assertIn(text, hero)

    def test_old_hero_texts_are_gone(self):
        hero = self.hero_html('/') + self.hero_html('/en/')
        for old in ['Python: от ужаса до понимания', 'Учитесь Python шаг за шагом',
                    'Короткие уроки и практика', 'Python: from horror to understanding',
                    'Learn Python step by step', 'hero__lead']:
            self.assertNotIn(old, hero)

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

    def test_hero_images_are_collected_and_hashed(self):
        import os

        html = self.client.get('/').content.decode()
        for name in ['hero-bg', 'hero-bg-1536', 'hero-bg-768',
                     'hero-author', 'hero-author-864', 'hero-author-432']:
            ext = 'png' if name in ('hero-bg', 'hero-author') else 'webp'
            pattern = rf'public/img/{name}\.[0-9a-f]{{12}}\.{ext}'
            found = re.search(r'/static/(' + pattern + ')', html)
            self.assertIsNotNone(found, pattern)
            self.assertTrue(os.path.exists(os.path.join(self.static_root, found.group(1))))


class ReviewsSectionTests(PublicPagesTestCase):
    """"Отзывы" come from the admin (Review): hidden while empty, and /en/ falls
    back to the Russian text."""

    def make_review(self, **kwargs):
        from api.models import Review
        defaults = dict(student_name='Анна', text_ru='Отличный курс!', is_published=True)
        defaults.update(kwargs)
        return Review.objects.create(**defaults)

    def test_section_and_nav_link_hidden_when_empty(self):
        self.make_review(student_name='Черновик', is_published=False)  # unpublished only
        course = self.make_course('Course')

        for url in ['/', '/en/', f'/course/{course.slug}/']:
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                self.assertNotIn('id="reviews"', html)
                self.assertNotIn('#reviews"', html)  # header link hidden
                self.assertNotIn('Черновик', html)

    def test_section_shown_when_filled(self):
        course = self.make_course('Python Basics')
        draft_course = self.make_course('Secret draft', is_published=False)
        self.make_review(student_name='Второй', order=2, source='Stepik',
                         source_url='https://stepik.org/review/1', course=course)
        self.make_review(student_name='Первый', order=1, course=draft_course)
        self.make_review(student_name='Скрытый', is_published=False)

        html = self.client.get('/').content.decode()

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

    def test_english_falls_back_to_russian(self):
        self.make_review(student_name='Без перевода', text_ru='Только по-русски', text_en='')
        self.make_review(student_name='С переводом', text_ru='По-русски', text_en='In English')

        html = self.client.get('/en/').content.decode()

        self.assertIn('Только по-русски', html)        # text_en empty → Russian
        self.assertIn('In English', html)
        self.assertNotIn('<p>По-русски</p>', html)
        self.assertIn('href="/en/#reviews">Reviews<', html)

    def test_review_text_is_escaped_and_keeps_paragraphs(self):
        self.make_review(text_ru='<b>bold</b>')
        self.make_review(text_ru='Начало отзыва.\n\nПродолжение.')
        html = self.client.get('/').content.decode()
        self.assertIn('&lt;b&gt;bold&lt;/b&gt;', html)
        self.assertIn('<p>Начало отзыва.</p>\n\n<p>Продолжение.</p>', html)


def make_author_profile(**kwargs):
    from api.models import AuthorProfile
    defaults = dict(name='Людмила', bio_ru='Старая биография.', photo='author/me.jpg')
    defaults.update(kwargs)
    return AuthorProfile.objects.create(**defaults)


class AuthorProfileAdminTests(PublicPagesTestCase):
    """One profile only; the form hides bio_ru / bio_en (the bio is in the template)."""

    def test_admin_allows_a_single_author_profile(self):
        from django.contrib.admin.sites import site
        from django.test import RequestFactory
        from api.models import AuthorProfile

        admin_user = User.objects.create_superuser('boss', 'b@example.com', 'x')
        request = RequestFactory().get('/admin/')
        request.user = admin_user
        model_admin = site._registry[AuthorProfile]

        self.assertTrue(model_admin.has_add_permission(request))
        make_author_profile()
        self.assertFalse(model_admin.has_add_permission(request))

    def test_admin_form_fields(self):
        from django.contrib.admin.sites import site
        from api.models import AuthorProfile

        self.assertEqual(site._registry[AuthorProfile].fields, ['name', 'name_en', 'photo', 'stepik_url'])


class AboutPageTests(PublicPagesTestCase):
    """"Об авторе" (/about/, /en/about/): the author's bio from the template, the
    uploaded photo or the static cut-out, and the links to it from every page."""

    KEY_PHRASES = [
        '<h2 class="about__name">Колесникова Людмила Сергеевна</h2>',
        '<em>Преподаватель, методист и автор курсов. Руководитель с 10-летним стажем.</em>',
        '<strong>Заслуженный наставник кружкового движения НТИ. Эксперт Школы наставников Сколково.</strong>',
        '<strong>Сегодня именно так я учу своих учеников.</strong>',
        '<strong>Гораздо важнее другое: хватит ли у тебя терпения и желания разобраться в том, '
        'что пока не получается.</strong>',
        '<strong>100% новых учеников приходят по рекомендациям.</strong>',
        'Более <strong>90% учеников</strong> проходят со мной полный образовательный цикл',
        '<strong>Победитель Stepik Birthday Hack</strong> в номинации «Самый социально значимый проект» (2023).',
        'Верю, что <strong>ошибки — это часть обучения, а не повод останавливаться.</strong>',
    ]

    def get(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.content.decode()

    def test_ru_and_en_pages_render_the_bio(self):
        for url in ['/about/', '/en/about/']:
            html = self.get(url)
            with self.subTest(url=url):
                for phrase in self.KEY_PHRASES:  # no English bio yet: Russian on /en/ too
                    self.assertIn(phrase, html)
                for heading in ['Немного обо мне', 'Мои ученики и результаты', 'Профессиональный опыт',
                                'Награды и достижения', 'Немного личного', 'Связаться со мной']:
                    self.assertRegex(html, rf'<h2 id="about-[a-z]+">{heading}</h2>')
                self.assertEqual(html.count('<ul>'), 4)

    def test_title_meta_and_heading_translated(self):
        ru, en = self.get('/about/'), self.get('/en/about/')
        self.assertIn('<title>Об авторе — Game Python</title>', ru)
        self.assertIn('<title>About the author — Game Python</title>', en)
        self.assertIn('class="about__title">Об авторе</h1>', ru)
        self.assertIn('class="about__title">About the author</h1>', en)
        self.assertIn('<meta name="description" content="Людмила Колесникова — преподаватель', ru)
        self.assertIn('<meta name="description" content="Lyudmila Kolesnikova — teacher', en)

    def test_external_links_open_in_a_new_tab(self):
        html = self.get('/about/')
        links = re.findall(r'<a href="https://[^"]+"[^>]*>', html)
        self.assertEqual(len(links), 4)
        for link in links:
            self.assertIn('target="_blank" rel="noopener noreferrer"', link)
        for url in ['https://t.me/kolesnikova1995', 'https://m.vk.com/ohota_na_python',
                    'https://t.me/ohota_na_python', 'https://stepik.org/users/32005180/profile']:
            self.assertIn(f'href="{url}"', html)

    def photo_html(self):
        html = self.get('/about/')
        return re.search(r'<div class="about__photo">.*?</div>', html, re.S).group(0)

    def test_static_cut_out_without_an_uploaded_photo(self):
        make_author_profile(photo='')  # a profile without a photo counts as none
        photo = self.photo_html()
        self.assertIn('public/img/hero-author-864.webp 864w', photo)
        self.assertIn('public/img/hero-author.png" width="864" height="1120"', photo)
        self.assertIn('alt="Колесникова Людмила Сергеевна"', photo)
        self.assertNotIn('loading=', photo)  # top of the page: never lazy

    def test_uploaded_photo_used_when_there_is_one(self):
        make_author_profile()
        photo = self.photo_html()
        self.assertIn('<img src="/media/author/me.jpg" width="360" height="480"', photo)
        self.assertNotIn('hero-author', photo)
        self.assertNotIn('loading=', photo)

    def test_nav_link_on_every_public_page(self):
        course = self.make_course('Course')
        for url, href, label in [('/', '/about/', 'Об авторе'),
                                 (f'/course/{course.slug}/', '/about/', 'Об авторе'),
                                 ('/en/', '/en/about/', 'About the author')]:
            html = self.get(url)
            with self.subTest(url=url):
                self.assertIn(f'<a class="site-nav__link" href="{href}">{label}</a>', html)
                for anchor in ['#catalog"', '#how"', '#faq"']:  # the existing items stay
                    self.assertIn(anchor, html)
        self.assertIn('href="/about/" aria-current="page">Об авторе</a>', self.get('/about/'))

    def test_hero_links_to_the_page(self):
        self.assertIn('<p class="hero__more"><a href="/about/">Подробнее обо мне →</a></p>', self.get('/'))
        self.assertIn('<p class="hero__more"><a href="/en/about/">More about me →</a></p>', self.get('/en/'))

    def test_landing_no_longer_has_the_author_section(self):
        make_author_profile(stepik_url='https://stepik.org/users/1')
        for url in ['/', '/en/']:
            html = self.get(url)
            with self.subTest(url=url):
                self.assertNotIn('id="author"', html)
                self.assertNotIn('author__', html)
                self.assertNotIn('/media/author/me.jpg', html)
                self.assertNotIn('Старая биография.', html)
                self.assertNotIn('https://stepik.org/users/1', html)
