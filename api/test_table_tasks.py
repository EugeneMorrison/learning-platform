"""Table grading, survey responses, private keys and historical selections."""

import copy
import uuid

from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .questions import build_context


class TableTaskTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='table_author', role='AUTHOR')
        cls.student = User.objects.create_user(username='table_student', role='STUDENT')
        cls.outsider = User.objects.create_user(username='table_outsider', role='STUDENT')
        cls.course = Course.objects.create(title='Tables', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Table lesson', order_index=1)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.rows = [{'id': str(uuid.uuid4()), 'text': text} for text in ('Australia', 'Austria')]
        cls.columns = [{'id': str(uuid.uuid4()), 'text': text} for text in ('English', 'German', 'Portuguese')]
        cls.correct = {cls.rows[0]['id']: [cls.columns[0]['id']], cls.rows[1]['id']: [cls.columns[1]['id']]}
        cls.block = Block.objects.create(lesson=cls.lesson, type='TABLE', order_index=1, content={
            'prompt': '<p>Select the official language.</p>', 'rows': cls.rows, 'columns': cls.columns,
            'correct_cells': cls.correct, 'multiple_answers': False, 'shuffle_rows': False, 'shuffle_columns': False,
            'any_answer_correct': False, 'feedback_correct': 'SUCCESS-COMMENT', 'feedback_incorrect': 'FAILURE-COMMENT',
        })

    def submit(self, selected=None, user=None, **extra):
        self.client.force_authenticate(user or self.student)
        return self.client.post('/api/progress/submit/', {
            'block': str(self.block.pk), 'is_correct': True,
            'answer': {'selected': copy.deepcopy(self.correct) if selected is None else selected,
                       'row_order': [row['id'] for row in self.rows], 'column_order': [column['id'] for column in self.columns],
                       'table_revision': self.block.updated_at.isoformat(), **extra},
        }, format='json')

    def test_wrong_then_corrected_selection_saves_both_attempts_and_feedback(self):
        wrong = {row['id']: [self.columns[2]['id']] for row in self.rows}
        response = self.submit(wrong, table_snapshot={'prompt': 'FORGED'}, correct_cells=wrong)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['is_correct'])
        self.assertEqual(response.data['feedback'], {'comment': 'FAILURE-COMMENT'})
        self.assertEqual(response.data['answer']['table_snapshot']['prompt'], self.block.content['prompt'])
        correct = self.submit()
        self.assertTrue(correct.data['is_correct'])
        self.assertEqual(correct.data['feedback'], {'comment': 'SUCCESS-COMMENT'})
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 2)
        first = copy.deepcopy(correct.data['answer'])
        for selected in (wrong, self.correct):
            self.assertFalse(self.submit(selected).data['recorded'])
        progress = Progress.objects.get(block=self.block, student=self.student)
        self.assertEqual(progress.attempts, 2)
        self.assertEqual(progress.answer, first)
        restored = self.client.get(f'/api/progress/course/{self.course.pk}/').data[0]
        self.assertEqual(restored['answer'], first)

    def test_multiple_requires_exact_sets_and_allows_a_row_with_no_correct_cells(self):
        self.block.content['multiple_answers'] = True
        self.block.content['correct_cells'] = {self.rows[0]['id']: [column['id'] for column in self.columns[:2]], self.rows[1]['id']: []}
        self.block.save()
        partial = {self.rows[0]['id']: [self.columns[0]['id']], self.rows[1]['id']: []}
        self.assertFalse(self.submit(partial).data['is_correct'])
        extra = {self.rows[0]['id']: [column['id'] for column in self.columns], self.rows[1]['id']: []}
        self.assertFalse(self.submit(extra).data['is_correct'])
        correct = {self.rows[0]['id']: [column['id'] for column in reversed(self.columns[:2])], self.rows[1]['id']: []}
        self.assertTrue(self.submit(correct).data['is_correct'])

    def test_shuffling_preserves_cell_identities_and_the_exact_display_order(self):
        self.block.content.update(shuffle_rows=True, shuffle_columns=True)
        self.block.save()
        row_order = [row['id'] for row in reversed(self.rows)]
        column_order = [column['id'] for column in reversed(self.columns)]
        response = self.submit(row_order=row_order, column_order=column_order)
        self.assertTrue(response.data['is_correct'])
        snapshot = response.data['answer']['table_snapshot']
        self.assertEqual([row['id'] for row in snapshot['rows']], row_order)
        self.assertEqual([column['id'] for column in snapshot['columns']], column_order)
        self.assertNotIn('correct_cells', snapshot)
        self.assertNotIn('SUCCESS-COMMENT', str(snapshot))

    def test_survey_accepts_any_valid_single_or_multiple_response_without_an_answer_key(self):
        self.block.content.update(any_answer_correct=True)
        self.block.content.pop('correct_cells')
        self.block.save()
        wrong = {row['id']: [self.columns[2]['id']] for row in self.rows}
        self.assertTrue(self.submit(wrong).data['is_correct'])
        Progress.objects.all().delete()
        self.block.content['multiple_answers'] = True
        self.block.save()
        empty = {row['id']: [] for row in self.rows}
        self.assertTrue(self.submit(empty).data['is_correct'])
        bad = {row['id']: ['not-a-column'] for row in self.rows}
        self.assertEqual(self.submit(bad).status_code, 400)

    def test_missing_unknown_duplicate_multi_single_and_stale_answers_are_rejected(self):
        bad_responses = [{}, {self.rows[0]['id']: []}, {row['id']: [] for row in self.rows},
                         {row['id']: [self.columns[0]['id'], self.columns[1]['id']] for row in self.rows},
                         {row['id']: [self.columns[0]['id']] * 2 for row in self.rows},
                         {row['id']: [True, {}] for row in self.rows},
                         {row['id']: [str(uuid.uuid4())] for row in self.rows}]
        for value in bad_responses:
            with self.subTest(selected=value):
                self.assertEqual(self.submit(value).status_code, 400)
        for revision in ('bad', None, 7, '2020-01-01T00:00:00Z'):
            self.assertEqual(self.submit(table_revision=revision).status_code, 400)
        self.assertEqual(self.submit(row_order=[self.rows[0]['id']] * 2).status_code, 400)
        self.assertEqual(self.submit(column_order=[]).status_code, 400)
        self.assertEqual(self.submit(row_order=[row['id'] for row in reversed(self.rows)]).status_code, 400)
        self.assertEqual(self.submit(column_order=[column['id'] for column in reversed(self.columns)]).status_code, 400)
        self.assertFalse(Attempt.objects.exists())
        self.assertFalse(Progress.objects.exists())

    def test_keys_comments_and_extra_fields_are_hidden_from_all_student_read_apis(self):
        self.block.content['solution'] = 'PRIVATE-SOLUTION'
        self.block.content['rows'][0]['correct_column'] = 'PRIVATE-LINK'
        self.block.save()
        self.client.force_authenticate(self.student)
        for url in (f'/api/blocks/{self.block.pk}/', f'/api/blocks/?lesson={self.lesson.pk}',
                    f'/api/lessons/{self.lesson.pk}/', f'/api/courses/{self.course.pk}/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            for secret in ('correct_cells', 'SUCCESS-COMMENT', 'FAILURE-COMMENT', 'PRIVATE-SOLUTION', 'PRIVATE-LINK'):
                self.assertNotIn(secret, str(response.data))
        context = build_context(self.block, self.student)
        self.assertNotIn('correct_cells', context['task'])
        self.assertNotIn('PRIVATE', str(context))
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(f'/api/blocks/{self.block.pk}/').data['content'], self.block.content)

    def test_editor_validation_and_duplication(self):
        self.client.force_authenticate(self.author)
        url = f'/api/blocks/{self.block.pk}/'
        content = copy.deepcopy(self.block.content)
        self.assertEqual(self.client.patch(url, {'content': content}, format='json').status_code, 200)
        changes = [{'prompt': ''}, {'rows': []}, {'columns': []}, {'rows': ['bad']},
                   {'multiple_answers': 1}, {'shuffle_rows': 'yes'}, {'shuffle_columns': []}, {'any_answer_correct': 'yes'},
                   {'feedback_correct': []}, {'feedback_incorrect': 7}, {'correct_cells': {}}, {'correct_cells': []},
                   {'correct_cells': {row['id']: [self.columns[0]['id']] * 2 for row in self.rows}},
                   {'correct_cells': {row['id']: ['bad'] for row in self.rows}}]
        for changeset in changes:
            with self.subTest(change=changeset):
                self.assertEqual(self.client.patch(url, {'content': {**content, **changeset}}, format='json').status_code, 400)
        for variant in ('empty_text', 'invalid_id', 'duplicate_id'):
            changed = copy.deepcopy(content)
            if variant == 'empty_text':
                changed['rows'][0]['text'] = ' '
            elif variant == 'invalid_id':
                changed['columns'][0]['id'] = 'invalid'
            else:
                changed['columns'][0]['id'] = changed['rows'][0]['id']
            self.assertEqual(self.client.patch(url, {'content': changed}, format='json').status_code, 400)
        survey = {**content, 'any_answer_correct': True, 'correct_cells': {}}
        self.assertEqual(self.client.patch(url, {'content': survey}, format='json').status_code, 200)
        duplicated = self.client.post(url + 'duplicate/', {}, format='json')
        self.assertEqual(duplicated.status_code, 201)
        self.assertEqual(duplicated.data['content'], survey)

    def test_access_counts_history_after_edits_and_retyping(self):
        self.assertEqual(self.submit(user=self.outsider).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/progress/submit/', {}, format='json').status_code, 401)
        self.client.force_authenticate(self.student)
        row = self.client.get('/api/lessons/outline/', {'course': str(self.course.pk)}).data[0]
        self.assertEqual((row['table_count'], row['task_count'], row['solved_count']), (1, 1, 0))
        self.assertFalse(self.client.get(f'/api/lessons/{self.lesson.pk}/').data['course_completed'])
        original = self.submit().data['answer']
        self.assertTrue(self.client.get(f'/api/lessons/{self.lesson.pk}/').data['course_completed'])
        self.block.content['rows'][0]['text'] = 'Renamed after submission'
        self.block.save()
        snapshot = build_context(self.block, self.student)['submission']['table_snapshot']
        self.assertEqual(snapshot, original['table_snapshot'])
        history = self.client.get(f'/api/progress/student/{self.student.pk}/course/{self.course.pk}/').data
        self.assertEqual(history['lessons'][0]['blocks'][0]['attempts_history'][0]['answer'], original)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.patch(f'/api/blocks/{self.block.pk}/', {
            'type': 'TEXT', 'content': {'html': '<p>Theory</p>'},
        }, format='json').status_code, 200)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())
