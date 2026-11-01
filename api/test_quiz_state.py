"""QUIZ display order, trusted snapshots and first-success compatibility."""

import copy
from unittest import mock

from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .questions import build_context


class QuizStateTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='quiz_author', role='AUTHOR')
        cls.student = User.objects.create_user(username='quiz_student', role='STUDENT')
        cls.other = User.objects.create_user(username='quiz_other', role='STUDENT')
        cls.outsider = User.objects.create_user(username='quiz_outsider', role='STUDENT')
        cls.course = Course.objects.create(title='Quiz course', author=cls.author)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Quiz lesson', order_index=1)
        for student in (cls.student, cls.other):
            Enrollment.objects.create(student=student, course=cls.course)
        cls.block = Block.objects.create(lesson=cls.lesson, type='QUIZ', order_index=1, content={
            'question': 'With what can & be used?',
            'options': ['values', 'keys', 'dictionaries', 'pairs'], 'correct_answer': 1,
            'explanation': 'Post-success explanation', 'shuffle_options': True,
            'solution': 'PRIVATE-SOLUTION', 'grading_secret': 'PRIVATE-GRADING',
        })

    def submit(self, user=None, selected=1, order=None, **extra):
        self.client.force_authenticate(user or self.student)
        answer = {'selected': selected, 'display_order': [3, 0, 1, 2] if order is None else order,
                  'quiz_revision': self.block.updated_at.isoformat().replace('+00:00', 'Z'), **extra}
        return self.client.post('/api/progress/submit/', {
            'block': str(self.block.pk), 'answer': answer, 'is_correct': True,
        }, format='json')

    def restored(self, user=None):
        self.client.force_authenticate(user or self.student)
        response = self.client.get(f'/api/progress/course/{self.course.pk}/')
        self.assertEqual(response.status_code, 200)
        return next(row for row in response.data if str(row['block']) == str(self.block.pk))

    def test_success_restores_exact_order_and_original_identity_on_repeated_visits(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['is_correct'])
        first = copy.deepcopy(response.data['answer'])
        self.assertEqual(first['selected'], 1)  # Displayed in position 3.
        self.assertEqual(first['display_order'], [3, 0, 1, 2])
        self.assertEqual(first['quiz_snapshot']['options'][first['selected']], 'keys')
        for _ in range(3):
            self.assertEqual(self.restored()['answer'], first)
        attempt = Attempt.objects.get(student=self.student, block=self.block)
        self.assertEqual(attempt.answer, first)

    def test_wrong_attempt_has_no_snapshot_or_explanation_then_correct_order_is_saved(self):
        wrong = self.submit(selected=0)
        self.assertFalse(wrong.data['is_correct'])
        self.assertNotIn('quiz_snapshot', wrong.data['answer'])
        self.assertEqual(wrong.data['feedback'], {})
        self.assertNotIn('Post-success explanation', wrong.content.decode())
        correct = self.submit(order=[2, 1, 3, 0])
        self.assertTrue(correct.data['is_correct'])
        self.assertEqual(self.restored()['answer']['display_order'], [2, 1, 3, 0])
        self.assertEqual(Progress.objects.get(block=self.block).attempts, 2)

    def test_practice_never_overwrites_first_success(self):
        self.submit()
        progress = Progress.objects.get(student=self.student, block=self.block)
        first = copy.deepcopy(progress.answer)
        when = progress.completed_at
        for selected in (0, 1):
            practice = self.submit(selected=selected, order=[1, 2, 0, 3])
            self.assertEqual(practice.data['is_correct'], selected == 1)
            self.assertFalse(practice.data['recorded'])
            progress.refresh_from_db()
            self.assertEqual(progress.answer, first)
            self.assertEqual(progress.completed_at, when)
            self.assertEqual(progress.attempts, 1)
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 1)

    def test_retry_order_is_saved_at_first_success_and_survives_practice_in_other_orders(self):
        wrong = self.submit(selected=0, order=[3, 0, 1, 2])
        self.assertFalse(wrong.data['is_correct'])
        first = self.submit(selected=1, order=[2, 3, 0, 1])
        self.assertTrue(first.data['recorded'])
        stored = copy.deepcopy(self.restored())
        for selected, order in ((0, [1, 0, 3, 2]), (1, [0, 1, 2, 3])):
            response = self.submit(selected=selected, order=order)
            self.assertEqual(response.data['is_correct'], selected == 1)
            self.assertFalse(response.data['recorded'])
            for _ in range(3):
                current = self.restored()
                self.assertEqual(current['answer'], stored['answer'])
                self.assertEqual(current['completed_at'], stored['completed_at'])
                self.assertEqual(Progress.objects.get(block=self.block).attempts, 2)
        self.assertEqual(stored['answer']['display_order'], [2, 3, 0, 1])
        self.assertEqual(stored['answer']['selected'], 1)
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 2)

    def test_students_save_independent_orders_and_cannot_read_each_others_progress(self):
        self.submit()
        self.submit(user=self.other, order=[1, 0, 2, 3])
        self.assertEqual(self.restored(self.student)['answer']['display_order'], [3, 0, 1, 2])
        self.assertEqual(self.restored(self.other)['answer']['display_order'], [1, 0, 2, 3])
        self.client.force_authenticate(self.student)
        response = self.client.get(f'/api/progress/student/{self.other.pk}/course/{self.course.pk}/')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.submit(user=self.outsider).status_code, 403)

    def test_client_snapshot_and_protected_fields_are_never_trusted(self):
        forged = {'question': 'FORGED', 'options': ['FORGED'], 'correct_answer': 0,
                  'explanation': 'FORGED', 'grading_secret': 'FORGED'}
        for selected in (0, 1):
            response = self.submit(selected=selected, quiz_snapshot=forged, explanation='FORGED', correct_answer=0)
            self.assertEqual(response.data['is_correct'], selected == 1)
            self.assertNotIn('FORGED', response.content.decode())
            self.assertNotIn('PRIVATE', response.content.decode())
            self.assertNotIn('correct_answer', response.content.decode())
        snapshot = self.restored()['answer']['quiz_snapshot']
        self.assertEqual(set(snapshot), {'question', 'options', 'explanation'})

    def test_malformed_orders_are_rejected_without_recording(self):
        for order in ([], [0, 1, 2], [0, 1, 2, 2], [0, 1, 2, 4], [-1, 1, 2, 3],
                      [False, 1, 2, 3], [0.0, 1, 2, 3], ['0', 1, 2, 3], '0123', {}, None):
            with self.subTest(order=order):
                response = self.submit(display_order=order)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())

    def test_invalid_selected_indices_are_rejected(self):
        for selected in (-1, 4, True, 1.0, '1', None):
            self.assertEqual(self.submit(selected=selected).status_code, 400)

    def test_revision_required_with_order_and_malformed_or_stale_revisions_are_rejected(self):
        for revision in (None, '', 'not-a-date', '2026-99-99', self.block.created_at.isoformat() + 'x',
                         '2000-01-01T00:00:00Z'):
            response = self.submit(quiz_revision=revision)
            self.assertEqual(response.status_code, 400, response.data)
        self.client.force_authenticate(self.student)
        for answer in ({'selected': 1, 'display_order': [0, 1, 2, 3]},
                       {'selected': 1, 'quiz_revision': self.block.updated_at.isoformat()}):
            response = self.client.post('/api/progress/submit/', {'block': str(self.block.pk), 'answer': answer}, format='json')
            self.assertEqual(response.status_code, 400)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())

    def test_author_edit_between_load_and_submit_rejects_stale_content(self):
        old_revision = self.block.updated_at.isoformat()
        self.block.content['question'] = 'New question'
        self.block.save()
        response = self.submit(quiz_revision=old_revision)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Автор изменил', response.data['detail'])
        self.assertFalse(Progress.objects.filter(block=self.block).exists())

    def test_edited_question_options_and_explanation_do_not_rewrite_saved_work(self):
        self.submit()
        original = copy.deepcopy(self.restored())
        self.block.content.update(question='Changed question', options=['new', 'different'],
                                  correct_answer=0, explanation='Changed explanation')
        self.block.save()
        restored = self.restored()
        self.assertEqual(restored['answer'], original['answer'])
        self.assertEqual(restored['feedback'], {'explanation': 'Post-success explanation'})
        self.assertTrue(restored['is_correct'])
        context = build_context(self.block, self.student)
        self.assertEqual(context['task']['question'], original['answer']['quiz_snapshot']['question'])
        self.assertEqual(context['task']['options'], original['answer']['quiz_snapshot']['options'])
        self.assertEqual(context['submission']['option'], 'keys')
        self.assertNotIn('explanation', context['task'])
        self.assertNotIn('correct_answer', str(context))
        # Practice uses the current version but leaves the historical success intact.
        response = self.submit(selected=0, order=[1, 0])
        self.assertTrue(response.data['is_correct'])
        self.assertFalse(response.data['recorded'])
        self.assertEqual(self.restored()['answer'], original['answer'])

    def test_absent_success_explanation_does_not_expose_a_later_one(self):
        self.block.content.pop('explanation')
        self.block.save()
        self.submit()
        self.block.content['explanation'] = 'New protected explanation'
        self.block.save()
        self.assertEqual(self.restored()['feedback'], {})

    def test_duplicate_option_texts_still_use_original_indices(self):
        self.block.content['options'] = ['same', 'same', 'other', 'last']
        self.block.save()
        self.assertFalse(self.submit(selected=0).data['is_correct'])
        self.assertTrue(self.submit(selected=1).data['is_correct'])
        self.assertEqual(self.restored()['answer']['selected'], 1)

    def test_shuffle_disabled_still_preserves_submitted_order(self):
        self.block.content['shuffle_options'] = False
        self.block.save()
        self.submit(order=[0, 1, 2, 3])
        self.assertEqual(self.restored()['answer']['display_order'], [0, 1, 2, 3])

    def test_legacy_clients_and_completed_answers_keep_their_shape_and_completion(self):
        self.client.force_authenticate(self.student)
        response = self.client.post('/api/progress/submit/', {
            'block': str(self.block.pk), 'answer': {'selected': 1},
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.restored()['answer'], {'selected': 1})
        self.assertTrue(self.restored()['is_correct'])
        self.assertFalse(self.submit().data['recorded'])
        self.assertEqual(self.restored()['answer'], {'selected': 1})

    def test_attempt_failure_rolls_back_progress(self):
        with mock.patch('api.quiz_state.Attempt.objects.create', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())

    def test_conditional_update_does_not_overwrite_a_concurrently_saved_success(self):
        self.submit()
        progress = Progress.objects.get(block=self.block)
        first = copy.deepcopy(progress.answer)
        stale = Progress(pk=progress.pk, student=self.student, block=self.block, lesson=self.lesson, is_correct=False)
        with mock.patch('api.quiz_state.Progress.objects.get_or_create', return_value=(stale, False)):
            response = self.submit(order=[0, 1, 2, 3])
        self.assertFalse(response.data['recorded'])
        progress.refresh_from_db()
        self.assertEqual(progress.answer, first)
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 1)
