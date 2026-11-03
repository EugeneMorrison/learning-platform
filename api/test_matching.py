"""Matching: private pairs, shuffling settings, empty items and saved work."""

import copy
import uuid

from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .questions import build_context


class MatchingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='match_author', role='AUTHOR')
        cls.student = User.objects.create_user(username='match_student', role='STUDENT')
        cls.outsider = User.objects.create_user(username='match_outsider', role='STUDENT')
        cls.course = Course.objects.create(title='Matching', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Match', order_index=1)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.pairs = [{'left': {'id': str(uuid.uuid4()), 'text': left},
                      'right': {'id': str(uuid.uuid4()), 'text': right}}
                     for left, right in [('Bulgaria', '<b>Sofia</b>'), ('India', 'New Delhi'),
                                         ('Unmatched A', ''), ('Unmatched B', ''), ('', 'Extra answer')]]
        cls.block = Block.objects.create(lesson=cls.lesson, type='MATCH', order_index=1, content={
            'prompt': '<p>Match countries and capitals. Leave extra items unmatched.</p>',
            'pairs': cls.pairs, 'html': True, 'keep_left_order': False,
            'feedback_correct': 'SUCCESS-COMMENT', 'feedback_incorrect': 'FAILURE-COMMENT',
        })

    def submit(self, left=None, right=None, user=None, **extra):
        self.client.force_authenticate(user or self.student)
        return self.client.post('/api/progress/submit/', {
            'block': str(self.block.pk), 'is_correct': True,
            'answer': {'left_order': [row['left']['id'] for row in self.pairs] if left is None else left,
                       'right_order': [row['right']['id'] for row in self.pairs] if right is None else right,
                       'match_revision': self.block.updated_at.isoformat(), **extra},
        }, format='json')

    def test_all_pairs_are_graded_on_server_with_comments_and_trusted_snapshots(self):
        ids = [row['right']['id'] for row in self.pairs]
        wrong_order = [ids[1], ids[0], *ids[2:]]
        wrong = self.submit(right=wrong_order, rows=[{'left': 'FORGED', 'right': 'FORGED'}], html=False)
        self.assertEqual(wrong.status_code, 200, wrong.data)
        self.assertFalse(wrong.data['is_correct'])
        self.assertEqual(wrong.data['feedback'], {'comment': 'FAILURE-COMMENT'})
        self.assertEqual(wrong.data['answer']['rows'][0]['right'], self.pairs[1]['right'])
        self.assertTrue(wrong.data['answer']['html'])
        correct = self.submit()
        self.assertTrue(correct.data['is_correct'])
        self.assertEqual(correct.data['feedback'], {'comment': 'SUCCESS-COMMENT'})
        self.assertEqual(correct.data['answer']['rows'], self.pairs)
        first = copy.deepcopy(correct.data['answer'])
        for order in (wrong_order, ids):
            self.assertFalse(self.submit(right=order).data['recorded'])
        progress = Progress.objects.get(student=self.student, block=self.block)
        self.assertEqual(progress.answer, first)
        self.assertEqual(progress.attempts, 2)
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 2)
        saved = self.client.get(f'/api/progress/course/{self.course.pk}/').data[0]
        self.assertEqual(saved['answer'], first)
        self.assertEqual(saved['feedback'], {'comment': 'SUCCESS-COMMENT'})

    def test_pair_order_is_irrelevant_and_blank_placeholders_are_interchangeable(self):
        left = [row['left']['id'] for row in reversed(self.pairs)]
        right = [row['right']['id'] for row in reversed(self.pairs)]
        right[1], right[2] = right[2], right[1]  # The two empty placeholders.
        result = self.submit(left=left, right=right)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data['is_correct'])
        self.assertEqual(result.data['answer']['left_order'], left)
        self.assertEqual(result.data['answer']['right_order'], right)

    def test_fixed_first_column_is_public_and_enforced_without_revealing_pairs(self):
        self.block.content['keep_left_order'] = True
        self.block.save()
        self.client.force_authenticate(self.student)
        content = self.client.get(f'/api/blocks/{self.block.pk}/').data['content']
        self.assertTrue(content['keep_left_order'])
        self.assertEqual(content['left'], [row['left'] for row in self.pairs])
        self.assertEqual(content['right'], sorted([row['right'] for row in self.pairs], key=lambda item: item['id']))
        reverse = {side: [row[side]['id'] for row in reversed(self.pairs)] for side in ('left', 'right')}
        self.assertEqual(self.submit(**reverse).status_code, 400)
        self.assertFalse(Attempt.objects.exists())
        self.assertTrue(self.submit().data['is_correct'])

    def test_incomplete_repeated_foreign_or_stale_submissions_are_rejected(self):
        ids = [row['left']['id'] for row in self.pairs]
        for side in ('left', 'right'):
            for order in ([], 'invalid', ids[:-1], [ids[0]] * len(ids), [True, {}, None, 2, []],
                          [str(uuid.uuid4()) for _ in ids]):
                with self.subTest(side=side, order=order):
                    self.assertEqual(self.submit(**{side: order}).status_code, 400)
        for revision in (None, 'invalid', '2020-01-01T00:00:00Z', 1):
            self.assertEqual(self.submit(match_revision=revision).status_code, 400)
        self.client.force_authenticate(self.student)
        for answer in (None, 'invalid', {}, [], {'left_order': []}):
            self.assertEqual(self.client.post('/api/progress/submit/', {
                'block': str(self.block.pk), 'answer': answer,
            }, format='json').status_code, 400)
        self.assertFalse(Progress.objects.exists())
        self.assertFalse(Attempt.objects.exists())

    def test_every_read_api_hides_pairs_comments_and_author_only_extra_fields(self):
        self.block.content['solution'] = 'PRIVATE-SOLUTION'
        self.block.content['pairs'][0]['left']['paired_with'] = 'PRIVATE-PAIR'
        self.block.save()
        self.client.force_authenticate(self.student)
        urls = [f'/api/blocks/{self.block.pk}/', f'/api/blocks/?lesson={self.lesson.pk}',
                f'/api/lessons/{self.lesson.pk}/', f'/api/courses/{self.course.pk}/']

        def check(value):
            if isinstance(value, list):
                for item in value:
                    check(item)
            elif isinstance(value, dict):
                if value.get('type') == 'MATCH':
                    public = value['content']
                    self.assertNotIn('pairs', public)
                    for side in ('left', 'right'):
                        expected = sorted([{'id': row[side]['id'], 'text': row[side]['text']} for row in self.pairs], key=lambda item: item['id'])
                        self.assertEqual(public[side], expected)
                for item in value.values():
                    check(item)

        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.data)
            for secret in ('SUCCESS-COMMENT', 'FAILURE-COMMENT', 'PRIVATE-SOLUTION', 'PRIVATE-PAIR'):
                self.assertNotIn(secret, str(response.data))
            check(response.data)
        context = build_context(self.block, self.student)
        self.assertNotIn('pairs', context['task'])
        self.assertNotIn('PRIVATE', str(context))
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(urls[0]).data['content'], self.block.content)

    def test_author_validation_accepts_one_sided_rows_and_rejects_broken_content(self):
        self.client.force_authenticate(self.author)
        url = f'/api/blocks/{self.block.pk}/'
        content = copy.deepcopy(self.block.content)
        self.assertEqual(self.client.patch(url, {'content': content}, format='json').status_code, 200)
        changes = [{'prompt': ''}, {'html': 'yes'}, {'keep_left_order': 1}, {'feedback_correct': []},
                   {'feedback_incorrect': 1}, {'pairs': []}, {'pairs': self.pairs[:1]}, {'pairs': ['a', 'b']}]
        for changeset in changes:
            self.assertEqual(self.client.patch(url, {'content': {**content, **changeset}}, format='json').status_code, 400)
        for broken in ('duplicate_id', 'invalid_id', 'no_right', 'empty_row', 'non_string', 'empty_column'):
            value = copy.deepcopy(content)
            pair = value['pairs'][0]
            if broken == 'duplicate_id':
                pair['right']['id'] = pair['left']['id']
            elif broken == 'invalid_id':
                pair['left']['id'] = 'not-a-uuid'
            elif broken == 'no_right':
                del pair['right']
            elif broken == 'empty_row':
                pair['left']['text'] = pair['right']['text'] = ''
            elif broken == 'non_string':
                pair['left']['text'] = []
            else:
                for row in value['pairs']:
                    row['right']['text'] = ''
            with self.subTest(broken=broken):
                self.assertEqual(self.client.patch(url, {'content': value}, format='json').status_code, 400)
        duplicate = self.client.post(url + 'duplicate/', {}, format='json')
        self.assertEqual(duplicate.status_code, 201, duplicate.data)
        self.assertEqual(duplicate.data['type'], 'MATCH')
        self.assertEqual(duplicate.data['content'], content)

    def test_access_counts_history_and_type_changes(self):
        self.assertEqual(self.submit(user=self.outsider).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/progress/submit/', {}, format='json').status_code, 401)
        self.client.force_authenticate(self.student)
        outline = self.client.get('/api/lessons/outline/', {'course': str(self.course.pk)}).data[0]
        self.assertEqual((outline['match_count'], outline['task_count'], outline['solved_count']), (1, 1, 0))
        self.assertFalse(self.client.get(f'/api/lessons/{self.lesson.pk}/').data['course_completed'])
        self.submit()
        outline = self.client.get('/api/lessons/outline/', {'course': str(self.course.pk)}).data[0]
        self.assertEqual(outline['solved_count'], 1)
        self.assertTrue(self.client.get(f'/api/lessons/{self.lesson.pk}/').data['course_completed'])
        original = copy.deepcopy(self.pairs)
        self.block.content['pairs'][0]['left']['text'] = 'Edited after submission'
        self.block.save()
        context = build_context(self.block, self.student)
        self.assertEqual(context['submission']['rows'], original)
        self.assertNotIn('SUCCESS-COMMENT', str(context))
        history = self.client.get(f'/api/progress/student/{self.student.pk}/course/{self.course.pk}/').data
        self.assertEqual(history['lessons'][0]['blocks'][0]['attempts_history'][0]['answer']['rows'], original)
        self.client.force_authenticate(self.author)
        changed = self.client.patch(f'/api/blocks/{self.block.pk}/', {
            'type': 'TEXT', 'content': {'html': '<p>Theory</p>'},
        }, format='json')
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())

    def test_duplicate_labels_are_interchangeable(self):
        self.block.content['pairs'][1]['right']['text'] = self.block.content['pairs'][0]['right']['text']
        self.block.save()
        right = [row['right']['id'] for row in self.pairs]
        right[0], right[1] = right[1], right[0]
        self.assertTrue(self.submit(right=right).data['is_correct'])
