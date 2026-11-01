"""Multiple answers remain a setting of the standard QUIZ block."""

from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .questions import build_context


class MultipleChoiceTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='multi_author', role='AUTHOR')
        cls.student = User.objects.create_user(username='multi_student', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Lesson', order_index=1)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.block = Block.objects.create(lesson=cls.lesson, type='QUIZ', order_index=1, content={
            'question': 'Select two', 'options': ['a', 'b', 'c', 'd'],
            'multiple_answers': True, 'correct_answers': [0, 2], 'explanation': 'Why',
        })

    def submit(self, selected, order=None):
        self.client.force_authenticate(self.student)
        return self.client.post('/api/progress/submit/', {
            'block': str(self.block.pk), 'answer': {
                'selected': selected, 'display_order': order if order is not None else [3, 2, 1, 0],
                'quiz_revision': self.block.updated_at.isoformat(),
            },
        }, format='json')

    def test_only_exact_set_passes_and_first_success_survives_practice(self):
        for selected in ([0], [2], [0, 1, 2], [1, 3]):
            response = self.submit(selected)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertFalse(response.data['is_correct'])
            self.assertEqual(response.data['feedback'], {})
        response = self.submit([2, 0])
        self.assertTrue(response.data['is_correct'])
        self.assertEqual(response.data['feedback'], {'explanation': 'Why'})
        first = response.data['answer']
        self.assertEqual(first['selected'], [2, 0])
        self.assertEqual(first['quiz_snapshot']['multiple_answers'], True)
        self.assertNotIn('correct_answers', str(first))
        for selected in ([1], [0, 2]):
            self.assertFalse(self.submit(selected).data['recorded'])
        progress = Progress.objects.get(block=self.block)
        self.assertEqual(progress.answer, first)
        self.assertEqual(progress.attempts, 5)
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 5)
        restored = self.client.get(f'/api/progress/course/{self.course.pk}/').data[0]
        self.assertEqual(restored['answer'], first)
        self.assertEqual(restored['feedback'], {'explanation': 'Why'})

    def test_retry_and_practice_orders_never_replace_the_first_success(self):
        self.assertFalse(self.submit([0], order=[3, 0, 1, 2]).data['is_correct'])
        first = self.submit([2, 0], order=[1, 3, 0, 2])
        self.assertTrue(first.data['recorded'])
        stored = Progress.objects.get(block=self.block)
        answer, when = stored.answer, stored.completed_at
        for selected, order in (([1], [2, 0, 3, 1]), ([0, 2], [0, 1, 2, 3])):
            practice = self.submit(selected, order=order)
            self.assertEqual(practice.data['is_correct'], selected == [0, 2])
            self.assertFalse(practice.data['recorded'])
            for _ in range(3):
                restored = self.client.get(f'/api/progress/course/{self.course.pk}/').data[0]
                self.assertEqual(restored['answer'], answer)
                self.assertEqual(Progress.objects.get(block=self.block).attempts, 2)
            stored.refresh_from_db()
            self.assertEqual(stored.completed_at, when)
        self.assertEqual(answer['display_order'], [1, 3, 0, 2])
        self.assertEqual(answer['selected'], [2, 0])
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 2)

    def test_malformed_answers_are_rejected_without_recording(self):
        for selected in ([], 0, None, '0,2', [0, 0, 2], [True, 2], [0.0, 2], [-1, 2], [0, 4], [{}]):
            with self.subTest(selected=selected):
                self.assertEqual(self.submit(selected).status_code, 400)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())

    def test_answer_keys_hidden_from_students_and_question_context(self):
        self.client.force_authenticate(self.student)
        public = self.client.get(f'/api/blocks/{self.block.pk}/').data['content']
        self.assertTrue(public['multiple_answers'])
        self.assertNotIn('correct_answers', public)
        self.assertNotIn('explanation', public)
        self.submit([2, 0])
        self.block.content.update(options=['new', 'options'], multiple_answers=False, correct_answer=1)
        self.block.save()
        context = build_context(self.block, self.student)
        self.assertEqual(context['task']['options'], ['a', 'b', 'c', 'd'])
        self.assertIn('c', context['submission']['option'])
        self.assertIn('a', context['submission']['option'])
        self.assertNotIn('correct_answers', str(context))

    def test_author_can_save_multiple_answers_and_validation_rejects_bad_keys(self):
        self.client.force_authenticate(self.author)
        url = f'/api/blocks/{self.block.pk}/'
        valid = dict(self.block.content)
        response = self.client.patch(url, {'content': valid}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['type'], 'QUIZ')
        for correct in ([], [0, 0], [4], [-1], [True], [0.0], '0,2', None):
            with self.subTest(correct=correct):
                response = self.client.patch(url, {'content': {**valid, 'correct_answers': correct}}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        # A multi-select test can have just one correct choice, too.
        response = self.client.patch(url, {'content': {**valid, 'correct_answers': [0]}}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_legacy_single_answer_quiz_still_uses_scalar_indices(self):
        self.block.content = {'question': 'One', 'options': ['a', 'b', 'c', 'd'], 'correct_answer': 2}
        self.block.save()
        self.assertEqual(self.submit([2]).status_code, 400)
        self.assertFalse(self.submit(0).data['is_correct'])
        self.assertTrue(self.submit(2).data['is_correct'])
