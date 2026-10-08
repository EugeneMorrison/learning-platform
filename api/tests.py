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

from .models import Block, Course, Enrollment, Lesson, Progress, User
from .serializers import UserSerializer


class ReadAccessMatrixTests(APITestCase):
    """
    Who can read what (step 4e, Coursera-style):
    - course detail: published → everyone; unpublished → its author only;
    - lessons and blocks (list and detail): own courses (author) ∪ enrolled
      courses (student); anonymous → nothing. Outside access: list omits it,
      detail is 404.
    """

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.other_author = User.objects.create_user(username='other_author', password='x', role='AUTHOR')
        cls.enrolled = User.objects.create_user(username='enrolled', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        cls.courses = {}
        for kind, published, price in [('free', True, 0), ('paid', True, Decimal('1990')),
                                       ('unpublished', False, 0)]:
            course = Course.objects.create(title=f'{kind} course', author=cls.author,
                                           is_published=published, price=price)
            lesson = Lesson.objects.create(course=course, title=f'{kind} lesson', order_index=1)
            block = Block.objects.create(lesson=lesson, type='TEXT', order_index=1,
                                         content={'html': f'<p>{kind}</p>'})
            # Enrolled in all three (a teacher may enrol students before publishing).
            Enrollment.objects.create(student=cls.enrolled, course=course)
            cls.courses[kind] = (course, lesson, block)

    PERSONAS = ['anonymous', 'outsider', 'enrolled', 'author', 'other_author']

    # persona → kinds of course whose LESSONS/BLOCKS they may read
    CONTENT_ACCESS = {
        'anonymous': set(),
        'outsider': set(),
        'enrolled': {'free', 'paid', 'unpublished'},
        'author': {'free', 'paid', 'unpublished'},
        'other_author': set(),
    }
    # persona → kinds of course whose DETAIL they may read
    COURSE_ACCESS = {
        'anonymous': {'free', 'paid'},
        'outsider': {'free', 'paid'},
        'enrolled': {'free', 'paid'},
        'author': {'free', 'paid', 'unpublished'},
        'other_author': {'free', 'paid'},
    }

    def login_as(self, persona):
        self.client.force_authenticate(None if persona == 'anonymous' else getattr(self, persona))

    def test_matrix(self):
        for persona in self.PERSONAS:
            self.login_as(persona)
            for kind, (course, lesson, block) in self.courses.items():
                can_read = kind in self.CONTENT_ACCESS[persona]
                with self.subTest(persona=persona, course=kind):
                    lessons = self.client.get(f'/api/lessons/?course={course.id}')
                    self.assertEqual(lessons.status_code, 200)
                    self.assertEqual([l['id'] for l in lessons.data],
                                     [str(lesson.id)] if can_read else [])

                    self.assertEqual(self.client.get(f'/api/lessons/{lesson.id}/').status_code,
                                     200 if can_read else 404)

                    blocks = self.client.get(f'/api/blocks/?lesson={lesson.id}')
                    self.assertEqual(blocks.status_code, 200)
                    self.assertEqual([b['id'] for b in blocks.data],
                                     [str(block.id)] if can_read else [])

                    self.assertEqual(self.client.get(f'/api/blocks/{block.id}/').status_code,
                                     200 if can_read else 404)

                    self.assertEqual(self.client.get(f'/api/courses/{course.id}/').status_code,
                                     200 if kind in self.COURSE_ACCESS[persona] else 404)

    def test_unfiltered_lists_contain_only_accessible_content(self):
        for persona in self.PERSONAS:
            self.login_as(persona)
            expected = {kind for kind in self.courses if kind in self.CONTENT_ACCESS[persona]}
            with self.subTest(persona=persona):
                lesson_ids = {l['id'] for l in self.client.get('/api/lessons/').data}
                block_ids = {b['id'] for b in self.client.get('/api/blocks/').data}
                self.assertEqual(lesson_ids, {str(self.courses[k][1].id) for k in expected})
                self.assertEqual(block_ids, {str(self.courses[k][2].id) for k in expected})

    def test_course_list_unchanged(self):
        self.login_as('anonymous')
        anon = {c['title'] for c in self.client.get('/api/courses/').data}
        self.login_as('author')
        author = {c['title'] for c in self.client.get('/api/courses/').data}

        self.assertEqual(anon, {'free course', 'paid course'})
        self.assertEqual(author, {'free course', 'paid course', 'unpublished course'})

    def test_lesson_404_carries_slug_only_for_published_courses(self):
        self.login_as('anonymous')
        for kind in ['free', 'paid']:
            course, lesson, _ = self.courses[kind]
            response = self.client.get(f'/api/lessons/{lesson.id}/')
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data['course_slug'], course.slug)

        _, unpublished_lesson, _ = self.courses['unpublished']
        for url in [f'/api/lessons/{unpublished_lesson.id}/',
                    '/api/lessons/3fa85f64-5717-4562-b3fc-2c963f66afa6/',
                    '/api/lessons/not-a-uuid/']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)
            self.assertNotIn('course_slug', response.data, url)

    def test_writes_unchanged_for_other_authors(self):
        # Other author: lessons/blocks of someone else's course are still not found for writes.
        self.login_as('other_author')
        _, lesson, block = self.courses['free']

        self.assertEqual(self.client.patch(f'/api/lessons/{lesson.id}/', {'title': 'Hacked'},
                                           format='json').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/blocks/{block.id}/').status_code, 404)
        lesson.refresh_from_db()
        self.assertEqual(lesson.title, 'free lesson')

    def test_author_can_still_edit_own_content(self):
        self.login_as('author')
        _, lesson, block = self.courses['unpublished']

        self.assertEqual(self.client.patch(f'/api/lessons/{lesson.id}/', {'title': 'Renamed'},
                                           format='json').status_code, 200)
        self.assertEqual(self.client.patch(f'/api/blocks/{block.id}/', {'order_index': 2},
                                           format='json').status_code, 200)

    def test_own_progress_page_needs_content_access(self):
        course, _, _ = self.courses['free']
        for persona, expected in [('outsider', 404), ('enrolled', 200)]:
            self.login_as(persona)
            user = getattr(self, persona)
            response = self.client.get(f'/api/progress/student/{user.id}/course/{course.id}/')
            self.assertEqual(response.status_code, expected, persona)


class ProgressSubmitAccessTests(APITestCase):
    SUBMIT_URL = '/api/progress/submit/'

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.enrolled = User.objects.create_user(username='enrolled', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        lesson = Lesson.objects.create(course=course, title='Lesson', order_index=1)
        cls.quiz = Block.objects.create(lesson=lesson, type='QUIZ', order_index=1, content={
            'question': 'q', 'options': ['a', 'b'], 'correct_answer': 1})
        Enrollment.objects.create(student=cls.enrolled, course=course)

    def submit(self, user, block_id, answer=None):
        self.client.force_authenticate(user)
        body = {'answer': answer or {'selected': 1}}
        if block_id is not None:
            body['block'] = str(block_id)
        return self.client.post(self.SUBMIT_URL, body, format='json')

    def test_anonymous_gets_401(self):
        self.assertEqual(self.submit(None, self.quiz.id).status_code, 401)
        self.assertFalse(Progress.objects.exists())

    def test_missing_block_gets_400(self):
        self.assertEqual(self.submit(self.enrolled, None).status_code, 400)

    def test_unknown_block_gets_404(self):
        for block_id in ['3fa85f64-5717-4562-b3fc-2c963f66afa6', 'not-a-uuid']:
            self.assertEqual(self.submit(self.enrolled, block_id).status_code, 404, block_id)
        self.assertFalse(Progress.objects.exists())

    def test_not_enrolled_gets_403(self):
        response = self.submit(self.outsider, self.quiz.id)

        self.assertEqual(response.status_code, 403)
        self.assertIn('detail', response.data)
        self.assertFalse(Progress.objects.exists())

    def test_enrolled_student_submits_and_is_graded(self):
        response = self.submit(self.enrolled, self.quiz.id, {'selected': 1})

        self.assertEqual(response.status_code, 200)
        progress = Progress.objects.get(student=self.enrolled, block=self.quiz)
        self.assertTrue(progress.is_correct)

    def test_course_author_can_submit(self):
        self.assertEqual(self.submit(self.author, self.quiz.id).status_code, 200)

    def test_removed_progress_viewset_routes_do_not_write(self):
        own = Progress.objects.create(student=self.outsider, block=self.quiz, lesson=self.quiz.lesson,
                                      completed=False, is_correct=False)
        self.client.force_authenticate(self.outsider)
        body = {'block': str(self.quiz.id), 'lesson': str(self.quiz.lesson_id),
                'completed': True, 'is_correct': True}

        attempts = [
            self.client.post('/api/progress/', body, format='json'),
            self.client.post('/api/progress.json', body, format='json'),
            self.client.put(f'/api/progress/{own.id}/', body, format='json'),
            self.client.patch(f'/api/progress/{own.id}/', {'is_correct': True}, format='json'),
            self.client.post('/api/progress/submit.json', body, format='json'),
        ]

        for response in attempts:
            self.assertEqual(response.status_code, 404, response.request['PATH_INFO'])
        own.refresh_from_db()
        self.assertFalse(own.is_correct)
        self.assertEqual(Progress.objects.count(), 1)

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
