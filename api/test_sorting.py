"""Sorting tasks: private answer order, strict submissions and saved work."""

import copy
import uuid

from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User
from .questions import build_context


class SortingTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='sort_author', role='AUTHOR')
        cls.student = User.objects.create_user(username='sort_student', role='STUDENT')
        cls.outsider = User.objects.create_user(username='sort_outsider', role='STUDENT')
        cls.course = Course.objects.create(title='Sorting', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Sort', order_index=1)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        # Intentionally different from lexical ID order, so leaking the answer
        # through array order is observable in every student-facing response.
        cls.items = [{'id': 'ffffffff-ffff-4fff-bfff-ffffffffffff', 'text': '<code>  first</code>'},
                     {'id': '11111111-1111-4111-b111-111111111111', 'text': '<abbr title="second">B</abbr>'},
                     {'id': 'aaaaaaaa-aaaa-4aaa-baaa-aaaaaaaaaaaa', 'text': 'last<br>line'}]
        cls.block = Block.objects.create(lesson=cls.lesson, type='SORT', order_index=1, content={
            'prompt': '<p>Sort from first to last, top to bottom.</p>', 'items': cls.items, 'html': True,
            'feedback_correct': 'SUCCESS-COMMENT', 'feedback_incorrect': 'FAILURE-COMMENT',
        })

    def submit(self, order=None, user=None, **extra):
        self.client.force_authenticate(user or self.student)
        return self.client.post('/api/progress/submit/', {
            'block': str(self.block.pk), 'is_correct': True,
            'answer': {'order': order if order is not None else [item['id'] for item in self.items],
                       'sort_revision': self.block.updated_at.isoformat(), **extra},
        }, format='json')

    def test_exact_order_grading_comments_and_practice_preserve_first_success(self):
        wrong = self.submit([item['id'] for item in reversed(self.items)], items=[{'text': 'FORGED'}])
        self.assertEqual(wrong.status_code, 200, wrong.data)
        self.assertFalse(wrong.data['is_correct'])
        self.assertEqual(wrong.data['feedback'], {'comment': 'FAILURE-COMMENT'})
        self.assertEqual(wrong.data['answer']['items'], list(reversed(self.items)))
        right = self.submit()
        self.assertTrue(right.data['is_correct'])
        self.assertEqual(right.data['feedback'], {'comment': 'SUCCESS-COMMENT'})
        first = copy.deepcopy(right.data['answer'])
        self.assertEqual(first['items'], self.items)
        for order in ([item['id'] for item in reversed(self.items)], [item['id'] for item in self.items]):
            self.assertFalse(self.submit(order).data['recorded'])
        progress = Progress.objects.get(block=self.block, student=self.student)
        self.assertEqual(progress.answer, first)
        self.assertEqual(progress.attempts, 2)
        self.assertEqual(Attempt.objects.filter(block=self.block).count(), 2)
        restored = self.client.get(f'/api/progress/course/{self.course.pk}/').data[0]
        self.assertEqual(restored['answer'], first)
        self.assertEqual(restored['feedback'], {'comment': 'SUCCESS-COMMENT'})

    def test_malformed_or_stale_answers_do_not_create_attempts(self):
        ids = [item['id'] for item in self.items]
        for order in ([], ids[:2], ids + ids[:1], [ids[0]] * 3, [True, {}, None],
                      'abc', [str(uuid.uuid4()), *ids[:2]]):
            with self.subTest(order=order):
                self.assertEqual(self.submit(order).status_code, 400)
        for revision in ('bad', '2020-01-01T00:00:00Z', None, 5):
            self.assertEqual(self.submit(sort_revision=revision).status_code, 400)
        self.assertFalse(Attempt.objects.exists())
        self.assertFalse(Progress.objects.exists())

    def test_read_apis_hide_solution_order_and_both_comments(self):
        self.client.force_authenticate(self.student)
        urls = [f'/api/blocks/{self.block.pk}/', f'/api/blocks/?lesson={self.lesson.pk}',
                f'/api/lessons/{self.lesson.pk}/', f'/api/courses/{self.course.pk}/']
        public_items = sorted(self.items, key=lambda item: item['id'])
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertNotIn('SUCCESS-COMMENT', str(response.data))
            self.assertNotIn('FAILURE-COMMENT', str(response.data))
        public = self.client.get(urls[0]).data['content']
        self.assertEqual(public['items'], public_items)
        self.assertNotEqual(public['items'], self.items)
        self.assertEqual(build_context(self.block, self.student)['task']['items'], public_items)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get(urls[0]).data['content']['items'], self.items)

    def test_author_validation_and_duplicate_and_retype(self):
        self.client.force_authenticate(self.author)
        url = f'/api/blocks/{self.block.pk}/'
        content = copy.deepcopy(self.block.content)
        self.assertEqual(self.client.patch(url, {'content': content}, format='json').status_code, 200)
        invalid = [dict(content, prompt=''), dict(content, html='yes'), dict(content, feedback_correct=7),
                   dict(content, feedback_incorrect=[]), dict(content, items=[]),
                   dict(content, items=self.items[:1]), dict(content, items=['a', 'b']),
                   dict(content, items=[self.items[0], self.items[0]]),
                   dict(content, items=[dict(self.items[0], id='0'), self.items[1]]),
                   dict(content, items=[dict(self.items[0], text=' '), self.items[1]])]
        for value in invalid:
            with self.subTest(content=value):
                self.assertEqual(self.client.patch(url, {'content': value}, format='json').status_code, 400)
        duplicate = self.client.post(url + 'duplicate/', {}, format='json')
        self.assertEqual(duplicate.status_code, 201, duplicate.data)
        self.assertEqual(duplicate.data['type'], 'SORT')
        self.assertEqual(duplicate.data['content'], content)
        self.submit()
        self.client.force_authenticate(self.author)
        changed = self.client.patch(url, {'type': 'TEXT', 'content': {'html': '<p>Theory</p>'}}, format='json')
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())

    def test_access_progress_counts_and_question_snapshot_history(self):
        self.assertEqual(self.submit(user=self.outsider).status_code, 403)
        self.client.force_authenticate(self.student)
        outline = self.client.get('/api/lessons/outline/', {'course': str(self.course.pk)})
        self.assertEqual(outline.status_code, 200, outline.data)
        self.assertEqual(outline.data[0]['sort_count'], 1)
        self.assertEqual(outline.data[0]['task_count'], 1)
        self.assertEqual(outline.data[0]['solved_count'], 0)
        self.assertFalse(self.client.get(f'/api/lessons/{self.lesson.pk}/').data['course_completed'])
        self.submit()
        outline = self.client.get('/api/lessons/outline/', {'course': str(self.course.pk)}).data
        self.assertEqual(outline[0]['solved_count'], 1)
        self.assertTrue(self.client.get(f'/api/lessons/{self.lesson.pk}/').data['course_completed'])
        self.block.content['items'] = [dict(item, text='Edited') for item in self.items]
        self.block.save()
        context = build_context(self.block, self.student)
        self.assertEqual(context['submission']['items'], self.items)
        self.assertNotIn('SUCCESS-COMMENT', str(context))
        history = self.client.get(f'/api/progress/student/{self.student.pk}/course/{self.course.pk}/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data['lessons'][0]['blocks'][0]['attempts_history'][0]['answer']['items'], self.items)

    def test_identical_text_items_can_be_interchanged(self):
        self.block.content['items'][1]['text'] = self.block.content['items'][0]['text']
        self.block.save()
        ids = [item['id'] for item in self.items]
        self.assertTrue(self.submit([ids[1], ids[0], ids[2]]).data['is_correct'])
