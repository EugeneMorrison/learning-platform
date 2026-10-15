"""
Local sample data comes only from "manage.py seed_data" (production loads no
fixtures on start; see the Dockerfile). These tests pin down that the command
gives usable accounts and the lesson the docs and iframe_test.html link to.

Run with: python manage.py test api.test_seed_data
"""

import io
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from rest_framework.test import APITestCase

from .management.commands.seed_data import SAMPLE_LESSON_ID
from .models import Course, Enrollment, Lesson, User


class SeedDataTests(APITestCase):
    def seed(self):
        call_command('seed_data', stdout=io.StringIO())

    def login(self, username):
        return self.client.post('/api/auth/login/', {'username': username, 'password': 'password123'},
                                format='json')

    def test_accounts_log_in_with_the_documented_password(self):
        self.seed()
        for username, role in [('john', 'AUTHOR'), ('alice', 'STUDENT')]:
            response = self.login(username)
            with self.subTest(username=username):
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['user']['role'], role)

    def test_sample_course_and_lesson(self):
        self.seed()
        course = Course.objects.get(title='Python Basics')
        self.assertTrue(course.is_published)
        self.assertTrue(course.slug)  # the course page needs one
        self.assertEqual(course.author.username, 'john')
        self.assertTrue(Enrollment.objects.filter(student__username='alice', course=course).exists())

        lesson = Lesson.objects.get(pk=SAMPLE_LESSON_ID)
        self.assertEqual(lesson.course, course)
        self.assertEqual(lesson.blocks.count(), 3)
        # alice (enrolled) opens the documented test lesson.
        self.client.force_authenticate(User.objects.get(username='alice'))
        self.assertEqual(self.client.get(f'/api/lessons/{SAMPLE_LESSON_ID}/').status_code, 200)

    def test_running_twice_changes_nothing(self):
        self.seed()
        self.seed()
        self.assertEqual(User.objects.filter(username__in=['john', 'alice']).count(), 2)
        self.assertEqual(Course.objects.filter(title='Python Basics').count(), 1)
        self.assertEqual(Lesson.objects.filter(pk=SAMPLE_LESSON_ID).count(), 1)
        self.assertEqual(self.login('alice').status_code, 200)


class NoFixturesOnStartTests(APITestCase):
    """Production start must not reload sample data (it once overwrote users,
    their password hashes and course content on every container start)."""

    def test_dockerfile_loads_no_fixtures(self):
        dockerfile = (Path(settings.BASE_DIR) / 'Dockerfile').read_text(encoding='utf-8')
        self.assertNotIn('loaddata', dockerfile)
        self.assertNotIn('fixtures.json', dockerfile)

    def test_no_fixture_file_in_the_project(self):
        self.assertFalse((Path(settings.BASE_DIR) / 'fixtures.json').exists())
