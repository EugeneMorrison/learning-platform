"""
Tests for the server-rendered public pages (backend/views.py).

Run with: python manage.py test backend
"""

import re
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from api.models import Course, Lesson, User

NBSP = ' '


class PublicPagesTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')

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
        self.assertNotContains(response, 'course-card__old-price')

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
    def test_published_course_returns_200(self):
        course = self.make_course('Python basics')

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Python basics')
        self.assertContains(response, 'Страница курса скоро появится')

    def test_english_course_page(self):
        course = self.make_course('Python basics')

        response = self.client.get(f'/en/course/{course.slug}/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<html lang="en">')

    def test_unpublished_course_returns_404(self):
        course = self.make_course('Draft', is_published=False)

        response = self.client.get(reverse('course_detail', kwargs={'slug': course.slug}))

        self.assertEqual(response.status_code, 404)

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
