from unittest import mock

from django.db.models.query import QuerySet
from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User


class BlockReorderTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', role='AUTHOR')
        cls.other = User.objects.create_user(username='other', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Lesson', order_index=1)
        cls.blocks = [Block.objects.create(lesson=cls.lesson, type='TEXT', order_index=slot,
                                          content={'html': f'<p>{slot}</p>'}) for slot in (0, 5, 10, 20)]
        other_lesson = Lesson.objects.create(course=cls.course, title='Other', order_index=2)
        cls.elsewhere = Block.objects.create(lesson=other_lesson, type='TEXT', order_index=2, content={'html': 'Other'})
        Enrollment.objects.create(student=cls.student, course=cls.course)

    def reorder(self, block, position, user=None):
        self.client.force_authenticate(user or self.author)
        return self.client.post(f'/api/blocks/{block.id}/reorder/', {'new_order': position}, format='json')

    def ids(self):
        return list(Block.objects.filter(lesson=self.lesson).order_by('order_index').values_list('id', flat=True))

    def test_long_moves_in_both_directions_preserve_gaps_and_other_lessons(self):
        a, b, c, d = self.blocks
        response = self.reorder(a, 4)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ids(), [b.id, c.id, d.id, a.id])
        self.assertEqual([item['id'] for item in response.data], list(map(str, self.ids())))
        self.assertEqual([item['order_index'] for item in response.data], [0, 5, 10, 20])
        self.assertEqual(self.reorder(a, 1).status_code, 200)
        self.assertEqual(self.ids(), [a.id, b.id, c.id, d.id])
        self.elsewhere.refresh_from_db()
        self.assertEqual(self.elsewhere.order_index, 2)

    def test_reorder_preserves_content_revisions_progress_and_attempts(self):
        block = self.blocks[0]
        block.type = 'QUIZ'
        block.content = {'question': 'Q', 'options': ['A', 'B'], 'correct_answer': 0}
        block.save()
        revision = block.updated_at
        progress = Progress.objects.create(student=self.student, block=block, lesson=self.lesson,
                                           answer={'selected': 0}, is_correct=True, completed=True)
        attempt = Attempt.objects.create(student=self.student, block=block, answer={'selected': 0}, is_correct=True)
        self.assertEqual(self.reorder(block, 3).status_code, 200)
        block.refresh_from_db()
        self.assertEqual(block.updated_at, revision)
        self.assertEqual(block.content['correct_answer'], 0)
        self.assertTrue(Progress.objects.filter(pk=progress.pk, is_correct=True).exists())
        self.assertTrue(Attempt.objects.filter(pk=attempt.pk).exists())

    def test_invalid_positions_do_not_change_order(self):
        original = self.ids()
        for value in (None, True, False, 0, -1, 1.5, [], {}, 'no', ''):
            with self.subTest(value=value):
                self.assertEqual(self.reorder(self.blocks[0], value).status_code, 400)
                self.assertEqual(self.ids(), original)

    def test_positions_clamp_and_same_position_is_safe(self):
        self.assertEqual(self.reorder(self.blocks[0], 999).status_code, 200)
        self.assertEqual(self.ids()[-1], self.blocks[0].id)
        self.assertEqual(self.reorder(self.blocks[0], '4').status_code, 200)
        self.assertEqual(self.ids()[-1], self.blocks[0].id)

    def test_only_owner_can_reorder(self):
        self.assertEqual(self.reorder(self.blocks[0], 2, self.other).status_code, 404)
        self.assertEqual(self.reorder(self.blocks[0], 2, self.student).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'/api/blocks/{self.blocks[0].id}/reorder/',
                                         {'new_order': 2}, format='json').status_code, 401)
        self.assertEqual(self.ids(), [block.id for block in self.blocks])

    def test_failure_during_reassignment_rolls_back_the_entire_move(self):
        original = QuerySet.update
        calls = 0

        def fail_partway(queryset, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 6:
                raise RuntimeError('Interrupted reorder')
            return original(queryset, **kwargs)

        with mock.patch.object(QuerySet, 'update', autospec=True, side_effect=fail_partway):
            with self.assertRaises(RuntimeError):
                self.reorder(self.blocks[0], 4)
        self.assertEqual(self.ids(), [block.id for block in self.blocks])
        self.assertEqual(list(Block.objects.filter(lesson=self.lesson).order_by('order_index')
                              .values_list('order_index', flat=True)), [0, 5, 10, 20])
