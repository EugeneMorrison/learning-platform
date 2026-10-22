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

    def test_all_courses_link_under_the_cards(self):
        self.make_course('Course')

        ru = self.client.get('/').content.decode()
        en = self.client.get('/en/').content.decode()

        self.assertIn('<a class="btn btn-secondary" href="/courses/">Все курсы →</a>', ru)
        self.assertIn('<a class="btn btn-secondary" href="/en/courses/">All courses →</a>', en)
        self.assertLess(ru.index('</ol>'), ru.index('href="/courses/">Все курсы'))

    def test_empty_state_when_no_published_courses(self):
        self.make_course('Draft only', is_published=False)

        response = self.client.get('/')

        self.assertContains(response, 'Курсы скоро появятся')
        self.assertNotContains(response, 'catalog__list')
        self.assertNotContains(response, 'Все курсы →')

    def test_english_catalog_heading(self):
        self.make_course('Основы', price=0)

        response = self.client.get('/en/')

        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, '<h1 id="catalog-title" class="catalog__title">Courses</h1>')
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


class CoursesCatalogPageTests(PublicPagesTestCase):
    """/courses/: every published course as a card with the data-* attributes
    public/js/catalog.js filters and sorts on; the filters are in the page but
    hidden until the script shows them."""

    def items(self, response):
        """data-* attributes of each card's <li>, in page order."""
        html = response.content.decode()
        return [dict(re.findall(r'data-([a-z-]+)="([^"]*)"', li))
                for li in re.findall(r'<li (data-title=.*?)>', html, re.S)]

    def test_lists_only_published_courses_under_ru_and_en(self):
        self.make_course('Опубликован')
        self.make_course('Черновик', is_published=False)
        for url in ['/courses/', '/en/courses/']:
            response = self.client.get(url)
            with self.subTest(url=url):
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.card_titles(response), ['Опубликован'])
                self.assertNotContains(response, 'Черновик')

    def test_server_order_is_sort_order_then_title(self):
        self.make_course('Б', sort_order=1)
        self.make_course('А', sort_order=1)
        self.make_course('В', sort_order=0)

        response = self.client.get('/courses/')

        self.assertEqual(self.card_titles(response), ['В', 'А', 'Б'])
        self.assertEqual([item['rank'] for item in self.items(response)], ['0', '1', '2'])

    def test_price_attributes_free_paid_and_discount(self):
        self.make_course('Free', price=0, sort_order=1)
        self.make_course('Paid', price=Decimal('1990.50'), sort_order=2)
        self.make_course('Discount', price=Decimal('1990'), old_price=Decimal('2990'), sort_order=3)
        self.make_course('Free was paid', price=0, old_price=Decimal('500'), sort_order=4)
        self.make_course('Same old price', price=Decimal('100'), old_price=Decimal('100'), sort_order=5)

        # Unlocalized in both languages: "1990.50", never "1990,50" or "1 990,50".
        for url in ['/courses/', '/en/courses/']:
            items = self.items(self.client.get(url))
            with self.subTest(url=url):
                self.assertEqual(
                    [(item['price'], item['old-price']) for item in items],
                    [('0.00', ''), ('1990.50', ''), ('1990.00', '2990.00'),
                     ('0.00', '500.00'), ('100.00', '100.00')],
                )

    def test_title_level_created_and_id_attributes(self):
        course = self.make_course('  Ёлочные   ИГРУШКИ ', level='INTERMEDIATE')
        no_level = self.make_course('Без уровня', sort_order=1)

        items = self.items(self.client.get('/courses/'))

        self.assertEqual(items[0]['title'], 'елочные игрушки')  # lower case, ё = е, single spaces
        self.assertEqual(items[0]['level'], 'intermediate')
        self.assertEqual(items[1]['level'], '')
        self.assertEqual(items[0]['id'], str(course.id))
        # Fixed-width UTC, so the script can compare them as strings.
        self.assertRegex(items[0]['created'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$')
        self.assertLessEqual(items[0]['created'], items[1]['created'])
        self.assertEqual(items[1]['id'], str(no_level.id))

    def test_filters_hidden_until_the_script_shows_them(self):
        self.make_course('Course')
        html = self.client.get('/courses/').content.decode()

        self.assertRegex(html, r'<form class="catalog-filters"[^>]* hidden')
        self.assertRegex(html, r'<div class="catalog-toolbar" hidden')
        self.assertRegex(html, r'<p class="catalog__empty" hidden[^>]*>Курсы не найдены</p>')
        self.assertRegex(html, r'<script src="/static/public/js/catalog\.js" defer></script>')
        self.assertIn('aria-live="polite"', html)

    def test_filter_texts_in_ru_and_en(self):
        self.make_course('Course')
        ru = self.client.get('/courses/')
        en = self.client.get('/en/courses/')

        for text in ['Каталог курсов', 'placeholder="Поиск курсов по названию"', 'Уровень', 'Любой',
                     'Начальный', 'Средний', 'Продвинутый', 'Доступ', 'Все', 'Бесплатные', 'Платные',
                     'Только со скидкой', 'Сбросить фильтры', 'Найдено:', 'Рекомендуемые',
                     'По сложности', 'Сначала новые', 'Сначала старые', 'Курсы не найдены']:
            self.assertContains(ru, text)
        for text in ['Course catalog', 'placeholder="Search courses by title"', 'Level', 'Any',
                     'Beginner', 'Intermediate', 'Advanced', 'Access', 'All', 'Free', 'Paid',
                     'Discounted only', 'Reset filters', 'Found:', 'Recommended', 'By difficulty',
                     'Newest first', 'Oldest first', 'No courses found']:
            self.assertContains(en, text)

    def test_level_pill_on_cards_with_a_level(self):
        self.make_course('Beginner course', level='BEGINNER', sort_order=1)
        self.make_course('Advanced course', level='ADVANCED', sort_order=2)
        self.make_course('No level', sort_order=3)

        ru = self.client.get('/courses/').content.decode()
        en = self.client.get('/en/courses/').content.decode()

        pill = '<span class="pill course-card__level"><span class="visually-hidden">{} </span>{}</span>'
        self.assertIn(pill.format('Уровень:', 'Начальный'), ru)
        self.assertIn(pill.format('Уровень:', 'Продвинутый'), ru)
        self.assertIn(pill.format('Level:', 'Beginner'), en)
        self.assertIn(pill.format('Level:', 'Advanced'), en)
        # One pill per card with a level; none for the course without one.
        cards = re.findall(r'<a class="course-card".*?</a>', ru, re.S)
        self.assertEqual([card.count('course-card__level') for card in cards], [1, 1, 0])

    def test_no_level_pill_on_the_landing_page(self):
        self.make_course('Beginner course', level='BEGINNER')
        for url in ['/', '/en/']:
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), 'course-card__level')

    def test_cards_have_no_step_badges_and_link_to_the_course_page(self):
        course = self.make_course('Linked')
        response = self.client.get('/courses/')

        self.assertNotContains(response, 'step-badge')
        self.assertContains(response, f'href="/course/{course.slug}/"')

    def test_empty_state_without_published_courses(self):
        self.make_course('Draft only', is_published=False)
        response = self.client.get('/courses/')

        self.assertContains(response, 'Курсы скоро появятся')
        self.assertNotContains(response, 'catalog-filters')
        self.assertNotContains(response, 'catalog.js')

    def test_query_count_does_not_grow_with_courses(self):
        # 2 = courses + published reviews (the header's «Отзывы» link).
        for n in range(1, 6):
            course = self.make_course(f'Course {n}', level='BEGINNER')
            Lesson.objects.create(course=course, title='Lesson', order_index=1)
        with self.assertNumQueries(2):
            response = self.client.get('/courses/')
        self.assertEqual(len(self.card_titles(response)), 5)

    def test_author_react_course_page_still_goes_to_the_spa(self):
        course = self.make_course('Course')
        response = self.client.get(f'/courses/{course.id}/')
        self.assertTemplateUsed(response, 'index.html')


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
        self.assertContains(ru, 'href="/courses/">← Все курсы<')
        self.assertContains(en, 'href="/en/courses/">← All courses<')

    def test_header_courses_link_goes_to_the_catalog_page(self):
        course = self.make_course('Python basics')

        ru = self.client.get(f'/course/{course.slug}/')
        en = self.client.get(f'/en/course/{course.slug}/')

        self.assertContains(ru, 'class="site-nav__link" href="/courses/">Курсы<')
        self.assertContains(en, 'class="site-nav__link" href="/en/courses/">Courses<')

    def test_landing_cards_link_to_course_page(self):
        course = self.make_course('Linked')

        response = self.client.get('/')

        self.assertContains(response, f'href="/course/{course.slug}/"')


class HeaderAuthLinkTests(PublicPagesTestCase):
    """The header login link ("Войти") is server-rendered; one inline script in
    base.html swaps every link carrying data-account-* for "Мой кабинет" when
    the React app's token is in localStorage (cosmetic only)."""

    # (link id, url, login label, account label)
    LINKS = [
        ('header-auth-link', '/', 'Войти', 'Мой кабинет'),
        ('header-auth-link', '/en/', 'Log in', 'My account'),
        ('header-auth-link', '/about/', 'Войти', 'Мой кабинет'),
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
        # At the end of <body>, so the header link exists when it runs.
        html = self.client.get('/').content.decode()
        script_at = html.index(self.login_script(html))
        self.assertLess(html.index('id="header-auth-link"'), script_at)

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
    """Author hero (public/includes/hero.html, on "Обо мне"): text + a two-layer
    picture (the violet illustration behind the author's cut-out), WebP with PNG
    fallbacks, loaded eagerly, alt translated."""

    CASES = [('/about/', 'ru', 'Людмила Колесникова'), ('/en/about/', 'en', 'Lyudmila Kolesnikova')]

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
        hero = self.hero_html('/about/')
        for old in ['code-card', 'lesson_01.py', 'hero__cat', 'cat-desk']:
            self.assertNotIn(old, hero)
        # The cat artwork stays in static files for later use.
        from django.contrib.staticfiles import finders
        self.assertIsNotNone(finders.find('public/img/cat-desk-800.webp'))

    TEXTS = {
        '/about/': ['<p class="hero__eyebrow">Привет!</p>',
              '<h1 id="hero-title" class="hero__title">Я Людмила Колесникова</h1>',
              '<p>Автор образовательного проекта учиЛКа.</p>',
              '<p>Уже более 10 лет я преподаю, создаю образовательные курсы и руковожу проектами.</p>',
              '<p>Здесь я делюсь своим опытом и знаниями: от программирования и создания игр '
              'до управления людьми и командами.</p>',
              '<p>Люблю объяснять сложное простыми словами и уверена, что ошибки — лучшие учителя, '
              'а не повод сдаваться!</p>',
              '<a class="btn btn-primary" href="/">Смотреть курсы</a>'],
        '/en/about/': ['<p class="hero__eyebrow">Hi!</p>',
                 '<h1 id="hero-title" class="hero__title">I\'m Lyudmila Kolesnikova</h1>',
                 '<p>Author of the educational project uchiLKa.</p>',
                 '<p>For more than 10 years I have been teaching, creating educational courses '
                 'and leading projects.</p>',
                 '<p>Here I share my experience and knowledge: from programming and game development '
                 'to managing people and teams.</p>',
                 '<p>I love explaining complex things in simple words, and I believe that mistakes '
                 'are the best teachers, not a reason to give up!</p>',
                 '<a class="btn btn-primary" href="/en/">Browse courses</a>'],
    }

    def test_author_texts_in_ru_and_en(self):
        for url, texts in self.TEXTS.items():
            hero = self.hero_html(url)
            with self.subTest(url=url):
                for text in texts:
                    self.assertIn(text, hero)

    def test_one_button_and_no_link_to_the_page_itself(self):
        for url in ['/about/', '/en/about/']:
            hero = self.hero_html(url)
            with self.subTest(url=url):
                self.assertEqual(hero.count('<a '), 1)  # "Смотреть курсы" only
                for gone in ['hero__more', 'hero-auth-link', 'data-account-href', '/login/']:
                    self.assertNotIn(gone, hero)

    def test_old_hero_texts_are_gone(self):
        hero = self.hero_html('/about/') + self.hero_html('/en/about/')
        for old in ['Python: от ужаса до понимания', 'Учитесь Python шаг за шагом',
                    'Короткие уроки и практика', 'Python: from horror to understanding',
                    'Learn Python step by step', 'hero__lead']:
            self.assertNotIn(old, hero)

    def test_no_remote_font_hosts(self):
        from django.contrib.staticfiles import finders

        for url in ['/', '/en/', '/about/']:
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

    def test_catalog_page_links_hashed_script_and_stylesheets(self):
        import os

        Course.objects.create(
            title='Course', is_published=True,
            author=User.objects.create_user(username='author', password='x', role='AUTHOR'),
        )
        html = self.client.get('/courses/').content.decode()

        for pattern in [r'src="/static/(public/js/catalog\.[0-9a-f]{12}\.js)" defer',
                        r'href="/static/(public/css/catalog\.[0-9a-f]{12}\.css)"',
                        r'href="/static/(public/css/courses\.[0-9a-f]{12}\.css)"']:
            found = re.search(pattern, html)
            with self.subTest(pattern=pattern):
                self.assertIsNotNone(found)
                self.assertTrue(os.path.exists(os.path.join(self.static_root, found.group(1))))

    def test_hero_images_are_collected_and_hashed(self):
        import os

        html = self.client.get('/about/').content.decode()
        for name in ['hero-bg', 'hero-bg-1536', 'hero-bg-768',
                     'hero-author', 'hero-author-864', 'hero-author-432']:
            ext = 'png' if name in ('hero-bg', 'hero-author') else 'webp'
            pattern = rf'public/img/{name}\.[0-9a-f]{{12}}\.{ext}'
            found = re.search(r'/static/(' + pattern + ')', html)
            self.assertIsNotNone(found, pattern)
            self.assertTrue(os.path.exists(os.path.join(self.static_root, found.group(1))))

    def test_icons_are_linked_by_hashed_names(self):
        import os

        html = self.client.get('/').content.decode()
        for rel, name in [('icon', r'favicon\.[0-9a-f]{12}\.ico'), ('icon', r'icon-192\.[0-9a-f]{12}\.png'),
                          ('apple-touch-icon', r'apple-touch-icon\.[0-9a-f]{12}\.png')]:
            found = re.search(rf'<link rel="{rel}"[^>]* href="/static/(public/img/{name})"', html)
            self.assertIsNotNone(found, name)
            self.assertTrue(os.path.exists(os.path.join(self.static_root, found.group(1))))
        # The React pages link the unhashed names; WhiteNoise keeps those too.
        for name in ['favicon.ico', 'icon-192.png', 'apple-touch-icon.png']:
            self.assertTrue(os.path.exists(os.path.join(self.static_root, 'public', 'img', name)), name)

    def test_root_favicon_with_debug_off(self):
        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/x-icon')


class FaviconTests(PublicPagesTestCase):
    """/favicon.ico is the real icon (not the React index.html), and every public
    page links the icon set."""

    def test_root_favicon_is_an_icon(self):
        from django.contrib.staticfiles import finders

        response = self.client.get('/favicon.ico')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/x-icon')
        body = b''.join(response.streaming_content)
        self.assertEqual(body[:4], b'\x00\x00\x01\x00')  # ICO header
        with open(finders.find('public/img/favicon.ico'), 'rb') as f:
            self.assertEqual(body, f.read())

    def test_icon_files_have_the_right_sizes(self):
        from django.contrib.staticfiles import finders
        from PIL import Image

        with Image.open(finders.find('public/img/favicon.ico')) as ico:
            self.assertEqual(sorted(ico.info['sizes']), [(16, 16), (32, 32), (48, 48)])
        for name, size in [('icon-192.png', 192), ('icon-512.png', 512), ('apple-touch-icon.png', 180)]:
            with Image.open(finders.find(f'public/img/{name}')) as im:
                self.assertEqual(im.size, (size, size), name)

    def test_public_pages_link_the_icons(self):
        course = self.make_course('Course')
        for url in ['/', '/en/', '/about/', f'/course/{course.slug}/']:
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                self.assertIn('<link rel="icon" href="/static/public/img/favicon.ico" sizes="16x16 32x32 48x48">', html)
                self.assertIn('href="/static/public/img/icon-192.png" sizes="192x192">', html)
                self.assertIn('<link rel="apple-touch-icon" href="/static/public/img/apple-touch-icon.png">', html)
                self.assertNotIn('favicon.svg', html)


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
    """"Обо мне" (/about/, /en/about/): the author hero on top, then the author's
    bio from the template (no second photo), and the links to it from every page."""

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
        self.assertIn('<title>Обо мне — УЧЁБУС</title>', ru)
        self.assertIn('<title>About me — UCHEBUS</title>', en)
        # An h2: the hero above holds the page's only h1.
        self.assertIn('class="about__title">Обо мне</h2>', ru)
        self.assertIn('class="about__title">About me</h2>', en)
        for html in [ru, en]:
            self.assertEqual(html.count('<h1'), 1)
            self.assertIn('<h1 id="hero-title"', html)
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

    def test_hero_first_then_the_bio_without_a_second_photo(self):
        make_author_profile()  # an uploaded photo is no longer shown anywhere
        for url in ['/about/', '/en/about/']:
            html = self.get(url)
            main = html[html.index('<main>'):html.index('</main>')]
            with self.subTest(url=url):
                self.assertLess(main.index('<section class="hero"'), main.index('<article class="about"'))
                # The cut-out appears once: in the hero.
                self.assertEqual(main.count('<img class="hero__img"'), 1)
                self.assertEqual(main.count('hero-author.png'), 1)
                self.assertNotIn('about__photo', html)
                self.assertNotIn('/media/author/me.jpg', html)
                self.assertIn('public/css/hero.css', html)

    def test_nav_link_on_every_public_page(self):
        course = self.make_course('Course')
        for url, href, label in [('/', '/about/', 'Обо мне'),
                                 (f'/course/{course.slug}/', '/about/', 'Обо мне'),
                                 ('/en/', '/en/about/', 'About me')]:
            html = self.get(url)
            with self.subTest(url=url):
                self.assertIn(f'<a class="site-nav__link" href="{href}">{label}</a>', html)
                self.assertIn('courses/">', html)  # the other items stay
        self.assertIn('href="/about/" aria-current="page">Обо мне</a>', self.get('/about/'))

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


class HeaderNavTests(PublicPagesTestCase):
    """The header nav (base.html): exactly Курсы · Отзывы · Обо мне, on every
    public page, in RU and EN. "Отзывы" is a link only while published reviews
    exist; before that it is plain text, never a link that leads nowhere."""

    CASES = [
        ('/', ['Курсы', 'Отзывы', 'Обо мне'], '/'),
        ('/about/', ['Курсы', 'Отзывы', 'Обо мне'], '/'),
        ('/courses/', ['Курсы', 'Отзывы', 'Обо мне'], '/'),
        ('/en/', ['Courses', 'Reviews', 'About me'], '/en/'),
        ('/en/about/', ['Courses', 'Reviews', 'About me'], '/en/'),
        ('/en/courses/', ['Courses', 'Reviews', 'About me'], '/en/'),
    ]

    def nav(self, url):
        html = self.client.get(url).content.decode()
        return re.search(r'<nav class="site-nav".*?</nav>', html, re.S).group(0)

    def items(self, nav):
        """Visible label of each <li>, without the screen-reader-only hint."""
        items = re.findall(r'<li>(.*?)</li>', nav, re.S)
        items = [re.sub(r'<span class="visually-hidden">.*?</span>', '', item, flags=re.S) for item in items]
        return [' '.join(re.sub(r'<[^>]+>', '', item).split()) for item in items]

    def test_exactly_three_items_in_order(self):
        for url, labels, _ in self.CASES:
            with self.subTest(url=url):
                self.assertEqual(self.items(self.nav(url)), labels)

    def test_links_from_every_page(self):
        # «Курсы» → the catalog page; «Отзывы» → the landing section (see below).
        course = self.make_course('Course')
        for url, _, landing in self.CASES + [(f'/course/{course.slug}/', None, '/')]:
            nav = self.nav(url)
            with self.subTest(url=url):
                self.assertIn(f'href="{landing}courses/"', nav)
                self.assertNotIn('#catalog', nav)
                self.assertIn(f'href="{landing}about/"', nav)
                self.assertNotRegex(nav, r'href="#')  # never a bare anchor

    def test_removed_items_are_gone(self):
        for url, _, _ in self.CASES:
            nav = self.nav(url)
            with self.subTest(url=url):
                for gone in ['#how', '#faq', 'Как это устроено', 'Вопросы', 'How it works', 'FAQ']:
                    self.assertNotIn(gone, nav)

    def test_reviews_is_text_until_a_review_is_published(self):
        from api.models import Review

        for url, _, _ in self.CASES:
            nav = self.nav(url)
            with self.subTest(url=url):
                self.assertNotIn('#reviews', nav)
                self.assertIn('site-nav__link--soon', nav)
        self.assertIn('<span class="visually-hidden"> (скоро)</span>', self.nav('/'))
        self.assertIn('<span class="visually-hidden"> (coming soon)</span>', self.nav('/en/'))

        Review.objects.create(student_name='Анна', text_ru='Отличный курс!', is_published=True)
        for url, labels, landing in self.CASES:
            nav = self.nav(url)
            with self.subTest(url=url, reviews=True):
                self.assertIn(f'<a class="site-nav__link" href="{landing}#reviews">{labels[1]}</a>', nav)
                self.assertNotIn('site-nav__link--soon', nav)
                self.assertEqual(self.items(nav), labels)

    def test_courses_is_marked_current_only_on_courses(self):
        self.assertIn('href="/courses/" aria-current="page">Курсы</a>', self.nav('/courses/'))
        self.assertIn('href="/en/courses/" aria-current="page">Courses</a>', self.nav('/en/courses/'))
        for url in ['/', '/about/', '/en/']:
            self.assertNotIn('href="/courses/" aria-current', self.nav(url))
            self.assertNotIn('href="/en/courses/" aria-current', self.nav(url))

    def test_about_is_marked_current_only_on_about(self):
        self.assertIn('href="/about/" aria-current="page"', self.nav('/about/'))
        self.assertIn('href="/en/about/" aria-current="page"', self.nav('/en/about/'))
        for url in ['/', '/en/']:
            self.assertNotIn('aria-current', self.nav(url))


class LandingCatTests(PublicPagesTestCase):
    """The decorative cat above the footer: landing page only."""

    def test_on_the_landing_page_in_ru_and_en(self):
        for url in ['/', '/en/']:
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                block = re.search(r'<div class="landing-cat">.*?</div>', html, re.S).group(0)
                self.assertIn('public/img/cat-desk-800.webp 800w', block)
                self.assertIn('public/img/cat-desk-1200.webp 1200w', block)
                img = re.search(r'<img[^>]*>', block).group(0)
                for attr in ['width="800" height="533"', 'alt=""', 'aria-hidden="true"', 'loading="lazy"']:
                    self.assertIn(attr, img)
                # After the last section, right before the footer.
                self.assertLess(html.index('id="catalog"'), html.index('class="landing-cat"'))
                self.assertLess(html.index('class="landing-cat"'), html.index('<footer'))
                self.assertNotIn('landing-cat', html[html.index('<footer'):])

    def test_not_on_other_pages(self):
        course = self.make_course('Course')
        for url in ['/about/', '/en/about/', f'/course/{course.slug}/']:
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                self.assertNotIn('landing-cat', html)
                self.assertNotIn('cat-desk', html)


class LandingHomeTests(PublicPagesTestCase):
    """The home page opens with the course catalog: no author hero, a short
    heading (the page's h1) and one subtitle line, in RU and EN."""

    HEADINGS = {
        '/': ('Курсы', 'Короткие уроки с практикой прямо в браузере. Выберите курс и начните.'),
        '/en/': ('Courses', 'Short lessons with hands-on practice right in your browser. '
                            'Pick a course and start.'),
    }

    def test_catalog_heading_and_subtitle(self):
        for url, (title, subtitle) in self.HEADINGS.items():
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                self.assertIn(f'<h1 id="catalog-title" class="catalog__title">{title}</h1>', html)
                self.assertIn(f'<p class="catalog__subtitle">{subtitle}</p>', html)
                self.assertEqual(html.count('<h1'), 1)

    def test_catalog_is_the_first_section_and_the_hero_is_gone(self):
        for url in self.HEADINGS:
            html = self.client.get(url).content.decode()
            main = html[html.index('<main>'):html.index('</main>')]
            with self.subTest(url=url):
                self.assertRegex(main, r'^<main>\s*<section id="catalog"')
                for gone in ['class="hero', 'hero-author', 'hero-bg', 'hero.css',
                             'hero-auth-link', 'Привет!', 'Hi!', 'Подробнее обо мне', 'More about me']:
                    self.assertNotIn(gone, html)

    def test_header_is_unchanged(self):
        html = self.client.get('/').content.decode()
        header = html[html.index('<header class="site-header">'):html.index('</header>')]
        for part in ['class="site-logo brand-logo"', 'class="site-nav"', 'class="lang-switch"',
                     'id="header-auth-link"', 'data-account-label="Мой кабинет"']:
            self.assertIn(part, header)


class CourseLoginGateTests(PublicPagesTestCase):
    """Course pages send visitors without the React app's token to the login page,
    with ?next= back to the course. The login state is only in localStorage, so
    the check is an inline script in <head>, before anything is painted."""

    def gate_script(self, html):
        head = html[:html.index('</head>')]
        scripts = [s for s in re.findall(r'<script>(.*?)</script>', head, re.S) if 'access_token' in s]
        self.assertEqual(len(scripts), 1, 'exactly one login gate in <head>')
        return scripts[0]

    def test_gate_in_head_of_course_pages(self):
        course = self.make_course('Gated')
        for url in [f'/course/{course.slug}/', f'/en/course/{course.slug}/']:
            script = self.gate_script(self.client.get(url).content.decode())
            with self.subTest(url=url):
                # Same key as frontend/src/api.js; storage access guarded.
                self.assertIn("window.localStorage.getItem('access_token')", script)
                self.assertIn('catch (e)', script)
                # replace(): the course page doesn't stay in history (Back won't loop).
                self.assertIn("window.location.replace('/login/?next=' + encodeURIComponent(next))", script)
                self.assertIn('window.location.pathname + window.location.search', script)

    def test_no_gate_on_other_public_pages(self):
        for url in ['/', '/en/', '/about/']:
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                self.assertNotIn('access_token', html[:html.index('</head>')])
                self.assertNotIn('/login/?next=', html)

    def test_cards_still_link_to_the_course_page(self):
        # Logged-in visitors keep the course page; the gate there handles the rest.
        course = self.make_course('Card')
        self.assertContains(self.client.get('/'), f'<a class="course-card" href="/course/{course.slug}/">')


class AuthPageNextTests(TestCase):
    """/login/ and /register/ (React pages) check ?next= on the server with
    url_has_allowed_host_and_scheme: a value leading off the site is dropped by
    a redirect to the bare page."""

    def get(self, url, **extra):
        from unittest import mock
        from django.http import HttpResponse

        # index.html is the React build (frontend/dist, not in Git): stand in for it.
        with mock.patch('backend.urls.render', return_value=HttpResponse('spa')):
            return self.client.get(url, **extra)

    def test_routes(self):
        from django.urls import resolve
        from backend.urls import auth_page_view

        for path in ['/login/', '/register/']:
            self.assertIs(resolve(path).func, auth_page_view)

    def test_same_site_next_is_kept(self):
        for page in ['/login/', '/register/']:
            for next_url in ['/course/python-basics/', '/en/course/python-basics/',
                             '/enroll/3fa85f64-5717-4562-b3fc-2c963f66afa6/',
                             'http://testserver/course/python-basics/']:
                with self.subTest(page=page, next=next_url):
                    response = self.get(page, data={'next': next_url})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, b'spa')

    def test_no_next_serves_the_page(self):
        self.assertEqual(self.get('/login/').status_code, 200)

    def test_off_site_next_is_dropped(self):
        for page in ['/login/', '/register/']:
            for next_url in ['https://evil.example/', '//evil.example/', '/\\evil.example/',
                             'http://evil.example/course/x/', 'javascript:alert(1)', '']:
                with self.subTest(page=page, next=next_url):
                    response = self.get(page, data={'next': next_url})
                    self.assertRedirects(response, page, fetch_redirect_response=False)

    def test_https_page_refuses_an_http_next(self):
        response = self.get('/login/', data={'next': 'http://testserver/course/x/'}, secure=True)
        self.assertRedirects(response, '/login/', fetch_redirect_response=False)


class BrandTests(PublicPagesTestCase):
    """The site name comes from settings.BRAND_NAMES only: УЧЁБУС on Russian
    pages, UCHEBUS on English ones, in the logo, footer, <title> and admin."""

    OLD_NAMES = ['Game Python', 'от ужаса до понимания', 'from horror to understanding']

    def pages(self):
        course = self.make_course('Python basics')
        # (url, name, logo link)
        return [('/', 'УЧЁБУС', '/'), ('/about/', 'УЧЁБУС', '/'), (f'/course/{course.slug}/', 'УЧЁБУС', '/'),
                ('/en/', 'UCHEBUS', '/en/'), ('/en/about/', 'UCHEBUS', '/en/'),
                (f'/en/course/{course.slug}/', 'UCHEBUS', '/en/')]

    def test_logo_footer_and_title(self):
        titles = {'/': '<title>УЧЁБУС</title>', '/en/': '<title>UCHEBUS</title>'}
        for url, name, home in self.pages():
            html = self.client.get(url).content.decode()
            with self.subTest(url=url):
                if 'Ё' in name:
                    # The cat logo (brand-logo.css): the text is still the real name.
                    before, _, after = name.partition('Ё')
                    self.assertIn(f'<a class="site-logo brand-logo" href="{home}" aria-label="{name} — на главную">'
                                  f'{before}<span class="brand-logo__yo"><span class="brand-logo__letter">Ё</span>'
                                  '<span class="brand-logo__cat" aria-hidden="true">', html)
                    self.assertIn(f'</svg></span></span>{after}</a>', html)
                else:
                    self.assertIn(f'<a class="site-logo" href="{home}">{name}</a>', html)
                self.assertIn(f'<p class="site-footer__name">{name}</p>', html)
                self.assertRegex(html, rf'<title>(.+ — )?{name}</title>')
                if url in titles:
                    self.assertIn(titles[url], html)
                for old in self.OLD_NAMES:
                    self.assertNotIn(old, html)

    def test_course_title_has_the_name(self):
        course = self.make_course('Python basics')
        self.assertContains(self.client.get(f'/course/{course.slug}/'), '<title>Python basics — УЧЁБУС</title>')
        self.assertContains(self.client.get(f'/en/course/{course.slug}/'), '<title>Python basics — UCHEBUS</title>')

    def test_admin_header_and_title(self):
        User.objects.create_superuser('boss', 'b@example.com', 'x')
        self.client.login(username='boss', password='x')
        html = self.client.get('/admin/').content.decode()
        self.assertIn('УЧЁБУС', html)
        self.assertNotIn('Django administration', html)
        self.assertNotIn('Администрирование Django', html)

    def test_one_setting_renames_everything(self):
        from django.test import override_settings

        with override_settings(BRAND_NAMES={'ru': 'НОВОЕ', 'en': 'NEW'}):
            ru = self.client.get('/').content.decode()
            en = self.client.get('/en/').content.decode()
        self.assertIn('<a class="site-logo" href="/">НОВОЕ</a>', ru)
        self.assertIn('<title>НОВОЕ</title>', ru)
        self.assertIn('<a class="site-logo" href="/en/">NEW</a>', en)
        self.assertNotIn('УЧЁБУС', ru + en)

    def test_react_constant_matches_the_russian_name(self):
        from django.conf import settings

        brand_js = open(settings.BASE_DIR / 'frontend' / 'src' / 'brand.js', encoding='utf-8').read()
        self.assertIn(f"export const BRAND_NAME = '{settings.BRAND_NAMES['ru']}';", brand_js)
        for old in self.OLD_NAMES:
            self.assertNotIn(old, brand_js)

    def test_logo_is_an_all_caps_wordmark(self):
        from django.contrib.staticfiles import finders

        css = open(finders.find('public/css/base.css'), encoding='utf-8').read()
        logo = re.search(r'\.site-logo \{(.*?)\}', css, re.S).group(1)
        self.assertIn('letter-spacing: var(--tracking-logo);', logo)
        self.assertIn('white-space: nowrap;', logo)
