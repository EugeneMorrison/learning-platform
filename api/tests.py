"""
API tests: public registration (always STUDENT), student self-enrolment
(POST /api/enrollments/), the teacher's enroll_student action, and access to
the code runner (/api/run-code/, /api/run-tests/).

Run with: python manage.py test api
"""

import subprocess
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from .models import Block, Course, Enrollment, Lesson, User
from .serializers import UserSerializer

REGISTER_URL = '/api/auth/register/'
RUN_CODE_URL = '/api/run-code/'
RUN_TESTS_URL = '/api/run-tests/'


def fake_run(stdout='2\n', returncode=0, stderr=''):
    """Stand-in for subprocess.run: the tests never start a real interpreter."""
    return mock.patch(
        'api.views.subprocess.run',
        return_value=subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr),
    )


class CodeRunnerAccessTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.other_author = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.enrolled = User.objects.create_user(username='enrolled', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        lesson = Lesson.objects.create(course=course, title='Lesson', order_index=1)
        cls.code_block = Block.objects.create(lesson=lesson, type='CODE', order_index=1, content={
            'prompt': 'p', 'starter_code': '', 'tests': [{'input': '1', 'expected': '2'}]})
        cls.text_block = Block.objects.create(
            lesson=lesson, type='TEXT', order_index=2, content={'html': '<p>x</p>'})
        Enrollment.objects.create(student=cls.enrolled, course=course)

    def setUp(self):
        cache.clear()  # throttle counters live in the default cache

    def run_code(self, user, block_id, url=RUN_CODE_URL):
        if user:
            self.client.force_authenticate(user)
        body = {'code': 'print(2)', 'stdin': '1', 'version': 'Python 3.12',
                'tests': [{'input': '1', 'expected': '2'}]}
        if block_id is not None:
            body['block_id'] = str(block_id)
        return self.client.post(url, body, format='json')

    def test_anonymous_gets_401(self):
        with fake_run() as run:
            for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                self.assertEqual(self.run_code(None, self.code_block.id, url).status_code, 401, url)
        run.assert_not_called()

    def test_not_enrolled_student_gets_403(self):
        with fake_run() as run:
            for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                self.assertEqual(self.run_code(self.outsider, self.code_block.id, url).status_code, 403, url)
        run.assert_not_called()

    def test_other_author_gets_403(self):
        with fake_run() as run:
            response = self.run_code(self.other_author, self.code_block.id)
        self.assertEqual(response.status_code, 403)
        run.assert_not_called()

    def test_enrolled_student_can_run_code_and_tests(self):
        with fake_run() as run:
            code = self.run_code(self.enrolled, self.code_block.id, RUN_CODE_URL)
            tests = self.run_code(self.enrolled, self.code_block.id, RUN_TESTS_URL)

        self.assertEqual(code.status_code, 200)
        self.assertEqual(code.data['stdout'], '2\n')
        self.assertEqual(tests.status_code, 200)
        self.assertEqual(tests.data['status'], 'success')
        self.assertEqual(run.call_count, 2)

    def test_course_author_can_run_code(self):
        with fake_run() as run:
            response = self.run_code(self.author, self.code_block.id)
        self.assertEqual(response.status_code, 200)
        run.assert_called_once()

    def test_unknown_or_malformed_block_gets_404(self):
        with fake_run() as run:
            for block_id in ['3fa85f64-5717-4562-b3fc-2c963f66afa6', 'not-a-uuid']:
                for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                    response = self.run_code(self.enrolled, block_id, url)
                    self.assertEqual(response.status_code, 404, (block_id, url))
        run.assert_not_called()

    def test_missing_block_id_gets_400(self):
        with fake_run() as run:
            response = self.run_code(self.enrolled, None)
        self.assertEqual(response.status_code, 400)
        run.assert_not_called()

    def test_non_code_block_gets_400(self):
        with fake_run() as run:
            for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                self.assertEqual(self.run_code(self.enrolled, self.text_block.id, url).status_code, 400, url)
        run.assert_not_called()

    def test_throttle_returns_429_when_exceeded(self):
        # The rate is read per request from this dict, so patching it overrides settings.
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'code_run': '3/min'}), fake_run():
            statuses = [self.run_code(self.enrolled, self.code_block.id, url).status_code
                        for url in [RUN_CODE_URL, RUN_TESTS_URL, RUN_CODE_URL, RUN_TESTS_URL]]
        # One shared budget for both endpoints: the 4th call in a minute is refused.
        self.assertEqual(statuses, [200, 200, 200, 429])

    def test_throttle_is_per_user(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'code_run': '1/min'}), fake_run():
            first = self.run_code(self.enrolled, self.code_block.id).status_code
            second = self.run_code(self.enrolled, self.code_block.id).status_code
            author = self.run_code(self.author, self.code_block.id).status_code
        self.assertEqual((first, second, author), (200, 429, 200))


class RegistrationRoleTests(APITestCase):
    def register(self, username, **extra):
        return self.client.post(
            REGISTER_URL, {'username': username, 'password': 'Sup3r-secret-pass', **extra},
            format='json')

    def test_client_supplied_role_is_ignored(self):
        for username, role in [('wants_author', 'AUTHOR'), ('wants_admin', 'ADMIN'),
                               ('bogus_role', 'SUPERUSER')]:
            response = self.register(username, role=role)

            self.assertEqual(response.status_code, 201, role)
            self.assertEqual(response.data['user']['role'], 'STUDENT', role)
            user = User.objects.get(username=username)
            self.assertEqual(user.role, 'STUDENT', role)
            self.assertFalse(user.is_staff or user.is_superuser, role)

    def test_no_role_registers_student(self):
        response = self.register('plain')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user']['role'], 'STUDENT')
        self.assertEqual(User.objects.get(username='plain').role, 'STUDENT')


class StudentCannotChangeOwnRoleTests(APITestCase):
    """There is no self-update endpoint; these pin that down and guard the serializer."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')

    def test_me_endpoint_is_read_only(self):
        self.client.force_authenticate(self.student)

        for method in ['put', 'patch', 'post']:
            response = getattr(self.client, method)(
                '/api/auth/me/', {'role': 'AUTHOR'}, format='json')
            self.assertEqual(response.status_code, 405, method)

        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'STUDENT')

    def test_registering_again_while_logged_in_does_not_change_role(self):
        self.client.force_authenticate(self.student)

        self.client.post(REGISTER_URL, {'username': 'student', 'password': 'y', 'role': 'AUTHOR'},
                         format='json')

        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'STUDENT')

    def test_user_serializer_role_is_read_only(self):
        serializer = UserSerializer(self.student, data={'role': 'ADMIN'}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'STUDENT')

ENROL_URL = '/api/enrollments/'


class SelfEnrolmentTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.admin = User.objects.create_user(username='admin', password='x', role='ADMIN')
        cls.free = Course.objects.create(
            title='Free course', author=cls.author, is_published=True, price=0)
        cls.paid = Course.objects.create(
            title='Paid course', author=cls.author, is_published=True, price=Decimal('1990'))
        cls.draft = Course.objects.create(
            title='Draft course', author=cls.author, is_published=False, price=0)

    def enrol(self, user, course_id):
        if user:
            self.client.force_authenticate(user)
        return self.client.post(ENROL_URL, {'course': str(course_id)}, format='json')

    def test_anonymous_gets_401(self):
        response = self.enrol(None, self.free.id)

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Enrollment.objects.exists())

    def test_author_gets_403(self):
        response = self.enrol(self.author, self.free.id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], 'Записаться на курс может только учащийся.')
        self.assertEqual(response.data['course_slug'], self.free.slug)
        self.assertFalse(Enrollment.objects.exists())

    def test_admin_role_gets_403(self):
        response = self.enrol(self.admin, self.free.id)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Enrollment.objects.exists())

    def test_unpublished_course_gets_404(self):
        response = self.enrol(self.student, self.draft.id)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['detail'], 'Курс не найден.')
        self.assertIsNone(response.data['course_slug'])
        self.assertFalse(Enrollment.objects.exists())

    def test_missing_or_malformed_course_gets_404(self):
        for course_id in ['3fa85f64-5717-4562-b3fc-2c963f66afa6', 'not-a-uuid', '']:
            response = self.enrol(self.student, course_id)
            self.assertEqual(response.status_code, 404, course_id)
        response = self.client.post(ENROL_URL, {}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Enrollment.objects.exists())

    def test_paid_course_gets_403(self):
        response = self.enrol(self.student, self.paid.id)

        self.assertEqual(response.status_code, 403)
        self.assertIn('платный', response.data['detail'])
        self.assertEqual(response.data['course_slug'], self.paid.slug)
        self.assertFalse(Enrollment.objects.exists())

    def test_role_is_checked_before_course(self):
        # An author asking for a missing course still gets the role error.
        response = self.enrol(self.author, '3fa85f64-5717-4562-b3fc-2c963f66afa6')

        self.assertEqual(response.status_code, 403)

    def test_free_published_course_creates_exactly_one_enrollment(self):
        response = self.enrol(self.student, self.free.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['course'], self.free.id)
        self.assertEqual(response.data['student'], self.student.id)
        self.assertEqual(
            Enrollment.objects.filter(student=self.student, course=self.free).count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_repeat_call_is_idempotent(self):
        first = self.enrol(self.student, self.free.id)
        second = self.enrol(self.student, self.free.id)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['id'], first.data['id'])
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_list_still_returns_own_enrollments(self):
        Enrollment.objects.create(student=self.student, course=self.free)
        other = User.objects.create_user(username='other', password='x', role='STUDENT')
        Enrollment.objects.create(student=other, course=self.free)
        self.client.force_authenticate(self.student)

        response = self.client.get(ENROL_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([e['student'] for e in response.data], [self.student.id])


class RemovedEnrolmentRoutesTests(APITestCase):
    """The old EnrollmentViewSet routes are gone, so nothing bypasses the rules above."""

    @classmethod
    def setUpTestData(cls):
        author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.free = Course.objects.create(
            title='Free course', author=author, is_published=True, price=0)
        cls.paid = Course.objects.create(
            title='Paid course', author=author, is_published=True, price=Decimal('1990'))

    def test_old_enroll_action_and_format_suffix_routes_are_gone(self):
        self.client.force_authenticate(self.student)
        enrollment = Enrollment.objects.create(student=self.student, course=self.free)

        attempts = [
            self.client.post('/api/enrollments/enroll/', {'course': str(self.paid.id)}, format='json'),
            self.client.post('/api/enrollments.json', {'course': str(self.paid.id)}, format='json'),
            self.client.patch(f'/api/enrollments/{enrollment.id}.json',
                              {'course': str(self.paid.id)}, format='json'),
        ]

        for response in attempts:
            self.assertEqual(response.status_code, 404, response.request['PATH_INFO'])
        self.assertFalse(Enrollment.objects.filter(course=self.paid).exists())


class TeacherEnrollStudentTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='alice', password='x', role='STUDENT')
        # Teachers may enrol anyone, including into paid and unpublished courses.
        cls.paid_draft = Course.objects.create(
            title='Paid draft', author=cls.author, is_published=False, price=Decimal('1990'))

    def test_teacher_can_enrol_a_student(self):
        self.client.force_authenticate(self.author)

        response = self.client.post(
            f'/api/courses/{self.paid_draft.id}/enroll_student/', {'username': 'alice'}, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Enrollment.objects.filter(student=self.student, course=self.paid_draft).exists())

    def test_student_cannot_use_teacher_action(self):
        self.client.force_authenticate(self.student)

        response = self.client.post(
            f'/api/courses/{self.paid_draft.id}/enroll_student/', {'username': 'alice'}, format='json')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Enrollment.objects.exists())
