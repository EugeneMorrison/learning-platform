"""Moving steps changes their lesson, while their identity and work survive."""

from unittest import mock
import uuid

from rest_framework.test import APITestCase

from .models import Attempt, Block, Comment, Course, CourseEdit, Enrollment, Lesson, Message, Progress, Thread, User
from .questions import build_context
from .serializers import MessageSerializer


class BlockMoveTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='move_author', role='AUTHOR')
        cls.other = User.objects.create_user(username='move_other', role='AUTHOR')
        cls.student = User.objects.create_user(username='move_student', role='STUDENT')
        cls.course = Course.objects.create(title='Python', author=cls.author, is_published=True)
        cls.source = Lesson.objects.create(course=cls.course, title='Data Input', order_index=3)
        cls.destination = Lesson.objects.create(course=cls.course, title='Variables', order_index=8)
        cls.empty = Lesson.objects.create(course=cls.course, title='Empty', order_index=12)
        cls.source_blocks = [Block.objects.create(lesson=cls.source, type='TEXT', order_index=position,
                                                  content={'html': str(position)}) for position in (0, 5, 10)]
        cls.block = cls.source_blocks[1]
        cls.block.type = 'QUIZ'
        cls.block.content = {'question': 'Which?', 'options': ['A', 'B'], 'correct_answer': 1}
        cls.block.save()
        cls.destination_blocks = [Block.objects.create(lesson=cls.destination, type='TEXT', order_index=position,
                                                       content={'html': str(position)}) for position in (0, 5)]
        cls.own_other_course = Course.objects.create(title='Another course', author=cls.author)
        cls.own_other_lesson = Lesson.objects.create(course=cls.own_other_course, title='Other course lesson', order_index=1)
        other_course = Course.objects.create(title='Foreign', author=cls.other)
        cls.foreign = Lesson.objects.create(course=other_course, title='Foreign lesson', order_index=1)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.progress = Progress.objects.create(student=cls.student, block=cls.block, lesson=cls.source,
                                               answer={'selected': 1}, completed=True, is_correct=True, attempts=2)
        cls.attempt = Attempt.objects.create(student=cls.student, block=cls.block, answer={'selected': 1}, is_correct=True)
        cls.thread = Thread.objects.create(block=cls.block, starter=cls.student)
        cls.comment = Comment.objects.create(thread=cls.thread, user=cls.student, text='Question')
        cls.message = Message.objects.create(sender=cls.student, receiver=cls.author, course=cls.course,
                                             block=cls.block, text='Question', context=build_context(cls.block, cls.student))

    def move(self, destination=None, user=None, **extra):
        self.client.force_authenticate(user or self.author)
        return self.client.post(f'/api/blocks/{self.block.pk}/move/', {
            'lesson': str((destination or self.destination).pk), 'expected_lesson': str(self.source.pk),
            'expected_updated_at': self.block.updated_at.isoformat(), **extra,
        }, format='json')

    def test_move_appends_and_preserves_block_content_revision_work_and_discussions(self):
        revision = self.block.updated_at
        content = self.block.content
        response = self.move()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['id'], str(self.block.pk))
        self.assertEqual(response.data['lesson'], self.destination.pk)
        self.assertEqual(response.data['lesson_title'], 'Variables')
        self.block.refresh_from_db()
        self.assertEqual(self.block.lesson_id, self.destination.pk)
        self.assertEqual(self.block.order_index, 6)
        self.assertEqual(self.block.content, content)
        self.assertEqual(self.block.updated_at, revision)
        self.assertEqual(list(self.source.blocks.values_list('order_index', flat=True)), [0, 10])
        self.assertEqual(list(self.destination.blocks.values_list('order_index', flat=True)), [0, 5, 6])
        self.progress.refresh_from_db()
        self.assertEqual(self.progress.lesson_id, self.destination.pk)
        self.assertEqual((self.progress.answer, self.progress.is_correct, self.progress.attempts), ({'selected': 1}, True, 2))
        self.assertEqual(Attempt.objects.get(pk=self.attempt.pk).block_id, self.block.pk)
        self.assertEqual(Thread.objects.get(pk=self.thread.pk).block.lesson_id, self.destination.pk)
        self.assertEqual(Comment.objects.get(pk=self.comment.pk).text, 'Question')

    def test_empty_destination_and_all_block_types(self):
        for kind in ['TEXT', 'QUIZ', 'CODE', 'FILL', 'SORT', 'MATCH', 'TABLE']:
            self.block.type = kind
            self.block.save()
            response = self.move(self.empty)
            self.assertEqual(response.status_code, 200, response.data)
            self.block.refresh_from_db()
            self.assertEqual((self.block.lesson_id, self.block.order_index), (self.empty.pk, 1))
            # Return through the same endpoint; no copies or progress resets.
            response = self.move(self.source, expected_lesson=str(self.empty.pk))
            self.assertEqual(response.status_code, 200, response.data)
            self.block.refresh_from_db()
            self.assertEqual(Block.objects.count(), 5)
            self.assertEqual(Progress.objects.count(), 1)
            self.assertEqual(Attempt.objects.count(), 1)

    def test_invalid_same_lesson_cross_course_and_foreign_destinations_are_safe(self):
        for value in ('bad', None, [], str(uuid.uuid4())):
            response = self.move(lesson=value)
            self.assertEqual(response.status_code, 404 if isinstance(value, str) and len(value) == 36 else 400)
        self.assertEqual(self.move(self.source).status_code, 400)
        self.assertEqual(self.move(self.own_other_lesson).status_code, 400)
        self.assertEqual(self.move(self.foreign).status_code, 404)
        self.block.refresh_from_db()
        self.assertEqual((self.block.lesson_id, self.block.order_index), (self.source.pk, 5))
        self.assertFalse(CourseEdit.objects.exists())

    def test_only_the_owner_can_move(self):
        self.assertEqual(self.move(user=self.student).status_code, 403)
        self.assertEqual(self.move(user=self.other).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'/api/blocks/{self.block.pk}/move/', {}, format='json').status_code, 401)

    def test_stale_content_or_source_and_repeated_requests_are_conflicts(self):
        self.assertEqual(self.move(expected_updated_at='2020-01-01T00:00:00Z').status_code, 409)
        self.assertEqual(self.move(expected_updated_at='invalid').status_code, 409)
        self.assertEqual(self.move(expected_lesson=str(self.empty.pk)).status_code, 409)
        self.assertFalse(CourseEdit.objects.exists())
        self.assertEqual(self.move().status_code, 200)
        self.assertEqual(self.move().status_code, 409)
        self.assertEqual(CourseEdit.objects.count(), 1)

    def test_any_failure_rolls_back_lesson_progress_and_history_together(self):
        with mock.patch('api.views.record_edit', side_effect=RuntimeError('History failed')):
            with self.assertRaises(RuntimeError):
                self.move()
        self.block.refresh_from_db()
        self.progress.refresh_from_db()
        self.assertEqual((self.block.lesson_id, self.block.order_index), (self.source.pk, 5))
        self.assertEqual(self.progress.lesson_id, self.source.pk)
        self.assertFalse(CourseEdit.objects.exists())

    def test_move_is_in_both_lesson_histories_and_full_block_history_follows_it(self):
        self.client.force_authenticate(self.author)
        self.client.patch(f'/api/blocks/{self.block.pk}/', {'content': self.block.content}, format='json')
        self.block.refresh_from_db()
        # A prior content edit should remain visible after the move.
        updated = {**self.block.content, 'question': 'Changed?'}
        self.client.patch(f'/api/blocks/{self.block.pk}/', {'content': updated}, format='json')
        self.block.refresh_from_db()
        self.assertEqual(self.move().status_code, 200)
        event = CourseEdit.objects.get(action='moved')
        self.assertEqual(event.before['lesson_title'], 'Data Input')
        self.assertEqual(event.after['lesson_title'], 'Variables')
        url = f'/api/courses/{self.course.pk}/history/'
        for lesson in (self.source, self.destination):
            rows = self.client.get(url, {'lesson': str(lesson.pk), 'action': 'moved'}).data['results']
            self.assertEqual([row['id'] for row in rows], [event.pk])
        rows = self.client.get(url, {'lesson': str(self.destination.pk), 'block': str(self.block.pk)}).data['results']
        self.assertEqual({row['action'] for row in rows}, {'updated', 'moved'})
        self.assertEqual(self.client.post(f'/api/blocks/{self.block.pk}/restore/', {'revision_id': event.pk}, format='json').status_code, 400)

    def test_counts_and_old_question_links_follow_the_current_location(self):
        self.assertEqual(self.move().status_code, 200)
        self.client.force_authenticate(self.student)
        rows = self.client.get('/api/lessons/outline/', {'course': str(self.course.pk)}).data
        by_id = {str(row['id']): row for row in rows}
        self.assertEqual((by_id[str(self.source.pk)]['task_count'], by_id[str(self.source.pk)]['solved_count']), (0, 0))
        self.assertEqual((by_id[str(self.destination.pk)]['task_count'], by_id[str(self.destination.pk)]['solved_count']), (1, 1))
        self.assertTrue(self.client.get(f'/api/lessons/{self.destination.pk}/').data['course_completed'])
        self.message.refresh_from_db()
        data = MessageSerializer(self.message).data
        self.assertEqual(data['block_lesson'], str(self.destination.pk))
        self.assertEqual(data['context']['lesson']['id'], str(self.source.pk))
        self.assertEqual(Progress.objects.get(pk=self.progress.pk).lesson_id, self.destination.pk)

    def test_a_run_started_before_the_move_records_progress_in_the_current_lesson(self):
        from .views import record_answer
        block_before_move = Block.objects.select_related('lesson').get(pk=self.block.pk)
        self.assertEqual(self.move().status_code, 200)
        progress = record_answer(self.author, block_before_move, {'selected': 1}, True)
        self.assertEqual(progress.lesson_id, self.destination.pk)
        self.assertEqual(self.progress.pk, Progress.objects.get(student=self.student, block=self.block).pk)
