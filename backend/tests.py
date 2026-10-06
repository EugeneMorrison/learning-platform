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
        self.assertContains(response, 'Learn to code step by step')
        self.assertContains(response, 'Lessons: 0')
        self.assertContains(response, 'Free')
        # Database content stays as entered (no model translations yet).
        self.assertContains(response, 'Основы')

    def test_catalog_query_count_does_not_grow_with_courses(self):
        def add_course(n):
            course = self.make_course(f'Course {n}')
            Lesson.objects.create(course=course, title='Lesson', order_index=1)

        add_course(1)
        with self.assertNumQueries(1):
            self.client.get('/')

        for n in range(2, 7):
            add_course(n)
        with self.assertNumQueries(1):
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

        with self.assertNumQueries(2):
            self.client.get(url)

        for n in range(2, 7):
            self.make_lesson(course, f'Lesson {n}', n, ['TEXT', 'QUIZ', 'CODE', 'FILL'])
        with self.assertNumQueries(2):
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
