from unittest import mock

from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, CourseEdit, Enrollment, Lesson, Progress, User


class EditHistoryTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', role='AUTHOR', first_name='Анна', last_name='Иванова')
        cls.other = User.objects.create_user(username='other', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', role='STUDENT')
        cls.course = Course.objects.create(title='Python', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(title='Strings', course=cls.course, order_index=1)
        cls.second = Lesson.objects.create(title='Lists', course=cls.course, order_index=2)
        cls.block = Block.objects.create(lesson=cls.lesson, type='TEXT', order_index=1, content={'html': '<p>Original</p>'})
        cls.quiz = Block.objects.create(lesson=cls.lesson, type='QUIZ', order_index=2,
                                        content={'question': 'Which?', 'options': ['a', 'b'], 'correct_answer': 1})
        Enrollment.objects.create(student=cls.student, course=cls.course)

    def setUp(self):
        self.client.force_authenticate(self.author)

    def history(self, **params):
        return self.client.get(f'/api/courses/{self.course.pk}/history/', params)

    def patch_block(self, html):
        return self.client.patch(f'/api/blocks/{self.block.pk}/', {'content': {'html': html}}, format='json')

    def restore(self, event, **extra):
        self.block.refresh_from_db()
        return self.client.post(f'/api/blocks/{self.block.pk}/restore/', {
            'revision_id': event.pk, 'expected_updated_at': self.block.updated_at.isoformat(), **extra,
        }, format='json')

    def test_block_update_retains_before_and_after_and_actor(self):
        self.assertEqual(self.patch_block('<p>Changed</p>').status_code, 200)
        event = CourseEdit.objects.get()
        self.assertEqual((event.kind, event.action, event.actor_name), ('block', 'updated', 'Анна Иванова'))
        self.assertEqual(event.before['content'], {'html': '<p>Original</p>'})
        self.assertEqual(event.after['content'], {'html': '<p>Changed</p>'})
        self.assertEqual(event.lesson_title, 'Strings')
        rows = self.history(block=str(self.block.pk)).data['results']
        self.assertEqual(len(rows), 1)
        self.assertNotIn('before', rows[0])
        detail = self.history(event=event.pk).data
        self.assertEqual(detail['before']['content'], event.before['content'])
        self.assertIn('content', detail['changed_fields'])

    def test_empty_updates_validation_errors_and_denied_requests_do_not_log(self):
        self.assertEqual(self.patch_block('<p>Original</p>').status_code, 200)
        self.assertEqual(self.client.patch(f'/api/blocks/{self.block.pk}/', {'content': {}}, format='json').status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.patch_block('Forbidden').status_code, 404)
        self.assertFalse(CourseEdit.objects.exists())

    def test_created_inserted_and_duplicated_blocks_each_log_once(self):
        body = {'lesson': str(self.lesson.pk), 'type': 'TEXT', 'content': {'html': '<p>New</p>'}, 'order_index': 3}
        self.assertEqual(self.client.post('/api/blocks/', body, format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/blocks/', {**body, 'insert_before': str(self.quiz.pk)}, format='json').status_code, 201)
        self.assertEqual(self.client.post(f'/api/blocks/{self.block.pk}/duplicate/').status_code, 201)
        self.assertEqual(list(CourseEdit.objects.order_by('id').values_list('action', flat=True)), ['created', 'created', 'duplicated'])

    def test_course_and_lesson_edits_are_recorded(self):
        course = self.client.post('/api/courses/', {'title': 'New course'}, format='json')
        self.assertEqual(course.status_code, 201)
        self.assertTrue(CourseEdit.objects.filter(course_id=course.data['id'], action='created').exists())
        self.assertEqual(self.client.patch(f'/api/courses/{self.course.pk}/', {'description': 'Description'}, format='json').status_code, 200)
        response = self.client.post('/api/lessons/', {'course': str(self.course.pk), 'title': 'New lesson', 'order_index': 3}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.patch(f'/api/lessons/{self.lesson.pk}/', {'title': 'Renamed'}, format='json').status_code, 200)
        self.assertEqual(self.history().status_code, 200)
        self.assertEqual(len(self.history(lesson=str(self.lesson.pk)).data['results']), 1)

    def test_reordering_records_the_complete_before_and_after_order(self):
        self.assertEqual(self.client.post(f'/api/lessons/{self.lesson.pk}/reorder/', {'new_order': 2}, format='json').status_code, 200)
        event = CourseEdit.objects.get(kind='lesson')
        self.assertEqual([item['id'] for item in event.before['order']], [str(self.lesson.pk), str(self.second.pk)])
        self.assertEqual([item['id'] for item in event.after['order']], [str(self.second.pk), str(self.lesson.pk)])
        self.assertEqual(self.client.post(f'/api/blocks/{self.block.pk}/reorder/', {'new_order': 2}, format='json').status_code, 200)
        event = CourseEdit.objects.get(kind='block')
        self.assertEqual(event.action, 'reordered')
        self.assertEqual(event.after['order'][-1]['id'], str(self.block.pk))
        self.client.post(f'/api/blocks/{self.block.pk}/reorder/', {'new_order': 2}, format='json')
        self.assertEqual(CourseEdit.objects.count(), 2)

    def test_deleted_items_remain_identifiable_in_course_history(self):
        block_id = self.block.pk
        self.assertEqual(self.client.delete(f'/api/blocks/{block_id}/').status_code, 204)
        event = CourseEdit.objects.get()
        self.assertEqual(event.target_id, block_id)
        self.assertIsNone(event.after)
        self.assertEqual(event.before['content']['html'], '<p>Original</p>')
        self.assertEqual(self.client.delete(f'/api/lessons/{self.lesson.pk}/').status_code, 204)
        event = CourseEdit.objects.get(kind='lesson')
        self.assertEqual(event.lesson_title, 'Strings')
        self.assertEqual(event.before['blocks'][0]['id'], str(self.quiz.pk))
        self.assertEqual(len(self.history().data['results']), 2)

    def test_history_is_owner_only_even_for_published_courses(self):
        self.client.patch(f'/api/blocks/{self.quiz.pk}/', {'content': {**self.quiz.content, 'correct_answer': 0}}, format='json')
        event = CourseEdit.objects.get()
        for user, code in ((self.other, 404), (self.student, 404), (None, 401)):
            self.client.force_authenticate(user)
            self.assertEqual(self.history().status_code, code)
            self.assertEqual(self.history(event=event.pk).status_code, code)

    def test_cursor_pagination_and_scope_do_not_repeat_or_leak_entries(self):
        for i in range(23):
            self.patch_block(f'<p>{i}</p>')
        first = self.history().data
        second = self.history(before=first['next_cursor']).data
        self.assertEqual((len(first['results']), len(second['results'])), (20, 3))
        self.assertFalse({item['id'] for item in first['results']} & {item['id'] for item in second['results']})
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(self.history(lesson=str(self.second.pk)).data['results'], [])
        self.assertEqual(self.history(block=str(self.quiz.pk), event=first['results'][0]['id']).status_code, 404)
        self.assertEqual(self.history(block='invalid').status_code, 400)

    def test_audit_failure_rolls_back_edit_including_answer_reset(self):
        Progress.objects.create(student=self.student, block=self.block, lesson=self.lesson, answer={}, is_correct=True)
        with mock.patch('api.edit_history.CourseEdit.objects.create', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.patch(f'/api/blocks/{self.block.pk}/', {'type': 'QUIZ', 'content': self.quiz.content}, format='json')
        self.block.refresh_from_db()
        self.assertEqual(self.block.type, 'TEXT')
        self.assertTrue(Progress.objects.filter(block=self.block).exists())

    def test_restore_previous_content_adds_event_and_keeps_current_order(self):
        self.patch_block('<p>New</p>')
        event = CourseEdit.objects.get()
        self.client.post(f'/api/blocks/{self.block.pk}/reorder/', {'new_order': 2}, format='json')
        response = self.restore(event, side='before')
        self.assertEqual(response.status_code, 200)
        self.block.refresh_from_db()
        self.assertEqual(self.block.content['html'], '<p>Original</p>')
        self.assertEqual(self.block.order_index, 2)
        restored = CourseEdit.objects.first()
        self.assertEqual((restored.action, restored.source_id), ('restored', event.pk))
        self.assertEqual(restored.before['content']['html'], '<p>New</p>')

    def test_restore_requires_fresh_revision_and_correct_block(self):
        self.patch_block('<p>New</p>')
        event = CourseEdit.objects.get()
        response = self.restore(event, side='before', expected_updated_at='2000-01-01T00:00:00Z')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.post(f'/api/blocks/{self.quiz.pk}/restore/', {
            'revision_id': event.pk, 'side': 'before'}, format='json').status_code, 404)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.restore(event).status_code, 404)

    def test_restoring_different_type_requires_answer_reset_confirmation(self):
        self.patch_block('<p>New</p>')
        original = CourseEdit.objects.get()
        self.client.patch(f'/api/blocks/{self.block.pk}/', {'type': 'QUIZ', 'content': self.quiz.content}, format='json')
        Progress.objects.create(student=self.student, block=self.block, lesson=self.lesson, answer={'selected': 1}, is_correct=True)
        Attempt.objects.create(student=self.student, block=self.block, answer={'selected': 1}, is_correct=True)
        response = self.restore(original)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.data['requires_reset'])
        self.assertTrue(Progress.objects.filter(block=self.block).exists())
        self.assertEqual(self.restore(original, confirm_reset=True).status_code, 200)
        self.assertFalse(Progress.objects.filter(block=self.block).exists())
        self.assertFalse(Attempt.objects.filter(block=self.block).exists())

    def test_deleted_or_order_only_snapshot_cannot_be_used_as_block_content(self):
        self.client.post(f'/api/blocks/{self.block.pk}/reorder/', {'new_order': 2}, format='json')
        self.assertEqual(self.restore(CourseEdit.objects.get()).status_code, 400)

    def test_course_history_can_filter_lesson_reordering(self):
        self.patch_block('Changed')
        self.client.post(f'/api/lessons/{self.lesson.pk}/reorder/', {'new_order': 2}, format='json')
        rows = self.history(kind='lesson', action='reordered').data['results']
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['kind'], rows[0]['action']), ('lesson', 'reordered'))
        self.assertEqual(self.history(kind='invalid').status_code, 400)
        self.assertEqual(self.history(event='9' * 100).status_code, 400)

    def test_saved_block_and_lesson_numbers_survive_later_reordering(self):
        Block.objects.create(lesson=self.lesson, type='CODE', order_index=5, content={'prompt': 'Code'})
        quiz = Block.objects.create(lesson=self.lesson, type='QUIZ', order_index=10, content=self.quiz.content)
        self.client.patch(f'/api/blocks/{quiz.pk}/', {'content': {**quiz.content, 'question': 'New question'}}, format='json')
        event = CourseEdit.objects.get()
        self.assertEqual((event.after['block_number'], event.after['lesson_number']), (2, 1))
        self.client.post(f'/api/blocks/{quiz.pk}/reorder/', {'new_order': 1}, format='json')
        self.client.post(f'/api/lessons/{self.lesson.pk}/reorder/', {'new_order': 2}, format='json')
        detail = self.history(event=event.pk).data
        self.assertEqual((detail['after']['block_number'], detail['lesson_number']), (2, 1))
        self.assertFalse(detail['number_is_current'])
        self.assertFalse(detail['lesson_number_is_current'])
        self.assertNotIn('block_number', detail['changed_fields'])
        self.client.patch(f'/api/blocks/{quiz.pk}/', {'content': self.quiz.content}, format='json')
        latest = CourseEdit.objects.first()
        self.assertEqual((latest.after['block_number'], latest.after['lesson_number']), (1, 2))

    def test_older_entries_show_current_numbers_without_rewriting_the_snapshot(self):
        self.patch_block('Changed')
        event = CourseEdit.objects.get()
        for value in (event.before, event.after):
            value.pop('block_number')
            value.pop('lesson_number')
        event.save(update_fields=['before', 'after'])
        detail = self.history(event=event.pk).data
        self.assertEqual(detail['after']['block_number'], 1)
        self.assertTrue(detail['after']['number_is_current'])
        self.assertEqual(detail['lesson_number'], 1)
        self.assertTrue(detail['lesson_number_is_current'])
        event.refresh_from_db()
        self.assertNotIn('block_number', event.after)
        self.client.delete(f'/api/blocks/{self.block.pk}/')
        self.assertIsNone(self.history(event=event.pk).data['block_number'])

    def test_numbering_is_preserved_in_each_side_of_a_type_change(self):
        Block.objects.create(lesson=self.lesson, type='TEXT', order_index=3, content={'html': 'Another theory'})
        self.client.patch(f'/api/blocks/{self.quiz.pk}/', {'type': 'TEXT', 'content': {'html': 'Now theory'}}, format='json')
        detail = self.history(event=CourseEdit.objects.get().pk).data
        self.assertEqual((detail['before']['type'], detail['before']['block_number']), ('QUIZ', 1))
        self.assertEqual((detail['after']['type'], detail['after']['block_number']), ('TEXT', 2))
