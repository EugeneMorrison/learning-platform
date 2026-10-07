"""
API tests: public registration (always STUDENT), student self-enrolment
(POST /api/enrollments/) and the teacher's enroll_student action.

Run with: python manage.py test api
"""

from decimal import Decimal

from rest_framework.test import APITestCase

from .models import Course, Enrollment, User
from .serializers import UserSerializer

REGISTER_URL = '/api/auth/register/'


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
