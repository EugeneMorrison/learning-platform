import subprocess
import uuid
from unittest import mock

from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .views import record_answer


class CodeSolutionsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', role='AUTHOR')
        cls.student = User.objects.create_user(username='viewer')
        cls.peer = User.objects.create_user(username='peer', first_name='Ada', last_name='Lovelace',
                                            email='private@example.com')
        cls.outsider = User.objects.create_user(username='outsider', role='AUTHOR')
        cls.course = Course.objects.create(title='Python', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Variables', order_index=1)
        cls.block = Block.objects.create(lesson=cls.lesson, type='CODE', order_index=1, content={
            'prompt': 'Print 1', 'starter_code': '# Ваш код здесь', 'solution': 'print(1)  # official\n',
            'header': '# PRIVATE HEADER', 'footer': '# PRIVATE FOOTER',
            'tests': [{'input': 'SECRET INPUT', 'expected': '1', 'visible': False}],
        })
        for user in (cls.student, cls.peer):
            Enrollment.objects.create(course=cls.course, student=user)
        record_answer(cls.peer, cls.block, {'code': 'print(1)  # peer\n', 'private': 'PRIVATE ANSWER METADATA'}, True)

    def setUp(self):
        cache.clear()
        self.client.force_authenticate(self.student)

    def get_solutions(self, **params):
        return self.client.get(f'/api/blocks/{self.block.pk}/solutions/', params)

    def solve(self, user=None):
        return record_answer(user or self.student, self.block, {'code': 'print(1)  # mine'}, True)

    def test_unsolved_wrong_answers_and_client_claims_do_not_unlock(self):
        self.assertEqual(self.get_solutions(is_correct=True).status_code, 403)
        record_answer(self.student, self.block, {'code': 'print(2)'}, False)
        response = self.get_solutions()
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('official', response.content.decode())
        self.assertNotIn('peer', response.content.decode())
        response = self.client.post('/api/progress/submit/', {
            'block': str(self.block.pk), 'answer': {'code': 'print(1)'}, 'is_correct': True,
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.get_solutions().status_code, 403)

    def test_course_access_is_required_even_with_saved_completion(self):
        self.solve(self.outsider)
        for user, expected in ((None, 401), (self.outsider, 404)):
            self.client.force_authenticate(user)
            self.assertEqual(self.get_solutions().status_code, expected)
        self.client.force_authenticate(self.student)
        self.solve()
        Enrollment.objects.filter(student=self.student).delete()
        self.assertEqual(self.get_solutions().status_code, 404)

    def test_only_code_tasks_have_solutions_and_missing_blocks_are_404(self):
        theory = Block.objects.create(lesson=self.lesson, type='TEXT', order_index=2, content={'html': 'Theory'})
        self.assertEqual(self.client.get(f'/api/blocks/{theory.pk}/solutions/').status_code, 400)
        self.assertEqual(self.client.get(f'/api/blocks/{uuid.uuid4()}/solutions/').status_code, 404)

    def test_official_and_one_accepted_solution_per_other_user_without_private_data(self):
        self.solve()
        self.solve(self.author)
        record_answer(self.peer, self.block, {'code': 'UNRECORDED PRACTICE'}, False)
        Attempt.objects.create(student=self.peer, block=self.block, answer={'code': 'ANOTHER ATTEMPT'}, is_correct=True)
        response = self.get_solutions()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['official_solution'], {
            'code': 'print(1)  # official\n', 'author_name': 'author',
        })
        self.assertEqual(response.data['results'], [{
            'id': str(Progress.objects.get(student=self.peer, block=self.block).pk),
            'code': 'print(1)  # peer\n', 'author_name': 'Ada Lovelace',
        }])
        self.assertIsNone(response.data['next_offset'])
        body = response.content.decode()
        for secret in ('SECRET INPUT', 'PRIVATE HEADER', 'PRIVATE FOOTER', 'PRIVATE ANSWER METADATA',
                       'private@example.com', 'UNRECORDED PRACTICE', 'ANOTHER ATTEMPT', '# mine'):
            self.assertNotIn(secret, body)

    def test_author_must_also_solve_before_viewing_peer_submissions(self):
        self.client.force_authenticate(self.author)
        self.assertEqual(self.get_solutions().status_code, 403)
        self.solve(self.author)
        self.assertEqual(self.get_solutions().status_code, 200)

    def test_official_solution_is_optional_and_remains_absent_from_regular_student_content(self):
        self.solve()
        response = self.client.get(f'/api/blocks/{self.block.pk}/')
        self.assertNotIn('solution', response.data['content'])
        for value in (None, '', '  \n', 123):
            self.block.content['solution'] = value
            self.block.save()
            self.assertIsNone(self.get_solutions().data['official_solution'])
        self.block.content.pop('solution')
        self.block.save()
        self.assertIsNone(self.get_solutions().data['official_solution'])

    def test_empty_state_ignores_wrong_other_tasks_and_malformed_legacy_answers(self):
        self.solve()
        Progress.objects.filter(student=self.peer).update(is_correct=False)
        other_block = Block.objects.create(lesson=self.lesson, type='CODE', order_index=2, content={})
        record_answer(self.peer, other_block, {'code': 'OTHER BLOCK'}, True)
        for index, answer in enumerate((None, [], 'text', {}, {'code': None}, {'code': 12}, {'code': '  '})):
            user = User.objects.create_user(username=f'legacy-{index}')
            record_answer(user, self.block, answer, True)
        self.block.content.pop('solution')
        self.block.save()
        response = self.get_solutions()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'official_solution': None, 'results': [], 'next_offset': None})

    def test_pagination_is_bounded_and_does_not_repeat_solutions(self):
        self.solve()
        for index in range(25):
            user = User.objects.create_user(username=f'solver-{index}')
            record_answer(user, self.block, {'code': f'print(1)  # {index}'}, True)
        first = self.get_solutions(limit=1000)
        self.assertEqual(len(first.data['results']), 20)
        self.assertEqual(first.data['next_offset'], 20)
        second = self.get_solutions(limit=1000, offset=first.data['next_offset'])
        self.assertEqual(len(second.data['results']), 6)
        self.assertIsNone(second.data['next_offset'])
        self.assertEqual(len({row['id'] for row in first.data['results'] + second.data['results']}), 26)

    def test_server_graded_success_unlocks_and_failed_practice_cannot_relock(self):
        payload = {'block_id': str(self.block.pk), 'code': 'print(1)', 'version': 'Python 3.12'}
        for stdout, expected in (('2', 403), ('1', 200), ('2', 200)):
            with mock.patch('api.views.run_python', return_value=subprocess.CompletedProcess([], 0, stdout, '')):
                response = self.client.post('/api/run-tests/', payload, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.get_solutions().status_code, expected)
        self.assertEqual(Progress.objects.get(student=self.student, block=self.block).answer, {'code': 'print(1)'})

    def test_type_change_resets_solution_access(self):
        self.solve()
        self.client.force_authenticate(self.author)
        response = self.client.patch(f'/api/blocks/{self.block.pk}/', {
            'type': 'TEXT', 'content': {'html': 'New theory'},
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.client.force_authenticate(self.student)
        self.assertEqual(self.get_solutions().status_code, 400)
