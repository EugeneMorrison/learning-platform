"""
Discussions (api/discussions.py): who may read which threads (the solved-block
rule, enforced on the server), enrolment, who may resolve / pin / delete, the
one-post-a-minute limit, and plain text only.

Run with: python manage.py test api.test_discussions
"""

from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .discussions import MAX_COMMENT_LENGTH
from .models import Block, Comment, Course, Enrollment, Lesson, Progress, Thread, User

PANEL_SOURCE = Path(settings.BASE_DIR, 'frontend', 'src', 'components', 'DiscussionPanel.jsx')


def make_thread(block, starter, text, pinned=False, replies=()):
    """A thread with its opening comment and (user, text) replies."""
    thread = Thread.objects.create(block=block, starter=starter, is_pinned=pinned)
    Comment.objects.create(thread=thread, user=starter, text=text)
    for user, reply in replies:
        Comment.objects.create(thread=thread, user=user, text=reply)
    return thread


def solve(student, block):
    Progress.objects.create(student=student, block=block, lesson=block.lesson, completed=True, is_correct=True)


class DiscussionTestCase(APITestCase):
    """
    One course. CODE block threads: pinned (by classmate), solver's, student's
    own (with a reply from solver). QUIZ: one thread by solver. `student` has
    solved nothing, `solver` has solved CODE and QUIZ.
    """

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.solver = User.objects.create_user(username='solver', password='x', role='STUDENT')
        cls.classmate = User.objects.create_user(username='classmate', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        cls.other_author = User.objects.create_user(username='other_author', password='x', role='AUTHOR')
        cls.course = Course.objects.create(title='Python basics', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Lists', order_index=1)
        cls.code = Block.objects.create(lesson=cls.lesson, type='CODE', order_index=1,
                                        content={'prompt': 'Print 1', 'tests': []})
        cls.quiz = Block.objects.create(lesson=cls.lesson, type='QUIZ', order_index=2,
                                        content={'question': 'Which?', 'options': ['a', 'b'], 'correct_answer': 1})
        cls.fill = Block.objects.create(lesson=cls.lesson, type='FILL', order_index=3,
                                        content={'prompt': 'Fill', 'template': 'x = {{1}}'})
        cls.text = Block.objects.create(lesson=cls.lesson, type='TEXT', order_index=4, content={'html': '<p>t</p>'})
        for user in (cls.student, cls.solver, cls.classmate):
            Enrollment.objects.create(student=user, course=cls.course)
        solve(cls.solver, cls.code)
        solve(cls.solver, cls.quiz)

        cls.pinned = make_thread(cls.code, cls.classmate, 'Подсказка для всех', pinned=True)
        cls.solvers = make_thread(cls.code, cls.solver, 'Моё решение: print(1)')
        cls.own = make_thread(cls.code, cls.student, 'Не понимаю условие',
                              replies=[(cls.solver, 'Перечитай второй абзац')])
        cls.quiz_thread = make_thread(cls.quiz, cls.solver, 'Ответ — b')
        # Long ago, so the setup's comments don't trip the rate limit.
        Comment.objects.update(created_at=timezone.now() - timedelta(days=1))

    def as_user(self, user):
        self.client.force_authenticate(user)
        return self.client

    def threads(self, user, block):
        return self.as_user(user).get(f'/api/blocks/{block.id}/threads/')

    def thread_ids(self, user, block):
        response = self.threads(user, block)
        self.assertEqual(response.status_code, 200)
        return [t['id'] for t in response.data['threads']]

    def start(self, user, block, text='Вопрос'):
        return self.as_user(user).post(f'/api/blocks/{block.id}/threads/', {'text': text}, format='json')

    def reply(self, user, thread, text='Ответ'):
        return self.as_user(user).post(f'/api/threads/{thread.id}/comments/', {'text': text}, format='json')

    def patch(self, user, thread, **data):
        return self.as_user(user).patch(f'/api/threads/{thread.id}/', data, format='json')

    def counts(self, user, lesson=None):
        return self.as_user(user).get('/api/discussions/counts/', {'lesson': str((lesson or self.lesson).id)})


class VisibilityTests(DiscussionTestCase):

    def test_unsolved_block_shows_only_pinned_and_own_threads(self):
        response = self.threads(self.student, self.code)
        self.assertEqual([t['id'] for t in response.data['threads']], [self.pinned.id, self.own.id])
        self.assertFalse(response.data['can_see_all'])
        self.assertEqual(response.data['hidden_count'], 1)
        self.assertNotIn('print(1)', str(response.data))

    def test_own_thread_comes_with_its_replies(self):
        own = next(t for t in self.threads(self.student, self.code).data['threads'] if t['id'] == self.own.id)
        self.assertEqual([c['text'] for c in own['comments']], ['Не понимаю условие', 'Перечитай второй абзац'])

    def test_solved_block_shows_all_threads(self):
        response = self.threads(self.solver, self.code)
        self.assertEqual({t['id'] for t in response.data['threads']}, {self.pinned.id, self.solvers.id, self.own.id})
        self.assertTrue(response.data['can_see_all'])
        self.assertEqual(response.data['hidden_count'], 0)

    def test_solving_the_block_opens_the_rest(self):
        Progress.objects.create(student=self.student, block=self.code, lesson=self.lesson,
                                completed=True, is_correct=False)
        self.assertNotIn(self.solvers.id, self.thread_ids(self.student, self.code))  # a wrong answer is not solving
        Progress.objects.filter(student=self.student, block=self.code).update(is_correct=True)
        self.assertIn(self.solvers.id, self.thread_ids(self.student, self.code))

    def test_course_author_sees_all_threads(self):
        response = self.threads(self.author, self.code)
        self.assertEqual(len(response.data['threads']), 3)
        self.assertTrue(response.data['can_see_all'])

    def test_quiz_follows_the_same_rule(self):
        self.assertEqual(self.thread_ids(self.student, self.quiz), [])
        self.assertEqual(self.thread_ids(self.solver, self.quiz), [self.quiz_thread.id])

    def test_hidden_thread_is_404_for_every_action(self):
        self.assertEqual(self.reply(self.student, self.solvers).status_code, 404)
        self.assertEqual(self.patch(self.student, self.solvers, is_resolved=True).status_code, 404)
        self.assertEqual(self.as_user(self.student).delete(f'/api/threads/{self.solvers.id}/').status_code, 404)
        comment = self.solvers.comments.first()
        self.assertEqual(self.as_user(self.student).delete(f'/api/comments/{comment.id}/').status_code, 404)
        self.assertEqual(self.solvers.comments.count(), 1)

    def test_pinned_thread_can_be_answered_before_solving(self):
        self.assertEqual(self.reply(self.student, self.pinned).status_code, 201)

    def test_pinned_first_then_open_then_resolved(self):
        Thread.objects.filter(pk=self.solvers.pk).update(is_resolved=True)
        newer = make_thread(self.code, self.classmate, 'Ещё вопрос')
        self.assertEqual(self.thread_ids(self.author, self.code),
                         [self.pinned.id, newer.id, self.own.id, self.solvers.id])

    def test_counts_are_what_the_viewer_may_read(self):
        code, quiz = str(self.code.id), str(self.quiz.id)
        self.assertEqual(self.counts(self.student).data['counts'], {code: 2})
        self.assertEqual(self.counts(self.solver).data['counts'], {code: 3, quiz: 1})
        self.assertEqual(self.counts(self.author).data['counts'], {code: 3, quiz: 1})

    def test_theory_blocks_have_no_discussions(self):
        self.assertEqual(self.threads(self.student, self.text).status_code, 400)
        self.assertEqual(self.start(self.student, self.text).status_code, 400)
        self.assertFalse(Thread.objects.filter(block=self.text).exists())


class EnrolmentTests(DiscussionTestCase):

    def test_outsiders_get_404(self):
        for user in (self.outsider, self.other_author):
            with self.subTest(user=user.username):
                self.assertEqual(self.threads(user, self.code).status_code, 404)
                self.assertEqual(self.start(user, self.code).status_code, 404)
                self.assertEqual(self.reply(user, self.pinned).status_code, 404)
                self.assertEqual(self.patch(user, self.pinned, is_resolved=True).status_code, 404)
                self.assertEqual(self.counts(user).status_code, 404)
        self.assertEqual(Comment.objects.count(), 5)

    def test_anonymous_gets_401(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f'/api/blocks/{self.code.id}/threads/').status_code, 401)
        self.assertEqual(self.client.post(f'/api/threads/{self.pinned.id}/comments/', {'text': 'x'}).status_code, 401)
        self.assertEqual(self.client.get('/api/discussions/counts/', {'lesson': str(self.lesson.id)}).status_code, 401)

    def test_leaving_the_course_ends_access_even_to_own_threads(self):
        Enrollment.objects.filter(student=self.student).delete()
        self.assertEqual(self.threads(self.student, self.code).status_code, 404)
        self.assertEqual(self.reply(self.student, self.own).status_code, 404)

    def test_enrolled_student_and_author_can_start_threads(self):
        response = self.start(self.student, self.fill, 'Что такое пропуск?')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['starter'], self.student.id)
        self.assertEqual([c['text'] for c in response.data['comments']], ['Что такое пропуск?'])
        self.assertEqual(self.start(self.author, self.fill).status_code, 201)

    def test_unknown_block_and_bad_lesson(self):
        self.assertEqual(self.as_user(self.student).get(
            '/api/blocks/00000000-0000-0000-0000-000000000000/threads/').status_code, 404)
        self.assertEqual(self.as_user(self.student).get(
            '/api/discussions/counts/', {'lesson': 'nope'}).status_code, 400)


class PermissionTests(DiscussionTestCase):

    def test_starter_and_course_author_can_resolve(self):
        response = self.patch(self.student, self.own, is_resolved=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_resolved'])
        self.assertEqual(response.data['resolved_by_name'], 'student')
        response = self.patch(self.author, self.own, is_resolved=False)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['resolved_by_name'])
        self.assertEqual(self.patch(self.author, self.solvers, is_resolved=True).status_code, 200)

    def test_others_cannot_resolve(self):
        # solver can read student's thread (solved the block) but didn't start it.
        self.assertEqual(self.patch(self.solver, self.own, is_resolved=True).status_code, 403)
        self.own.refresh_from_db()
        self.assertFalse(self.own.is_resolved)

    def test_only_course_author_can_pin(self):
        self.assertEqual(self.patch(self.student, self.own, is_pinned=True).status_code, 403)
        response = self.patch(self.author, self.solvers, is_pinned=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_pinned'])
        self.assertIn(self.solvers.id, self.thread_ids(self.student, self.code))  # pinned: open to all

    def test_patch_needs_a_boolean_field(self):
        self.assertEqual(self.patch(self.author, self.own).status_code, 400)
        self.assertEqual(self.patch(self.author, self.own, is_pinned='yes').status_code, 400)

    def test_can_flags_follow_the_viewer(self):
        own = next(t for t in self.threads(self.student, self.code).data['threads'] if t['id'] == self.own.id)
        self.assertEqual((own['can_resolve'], own['can_pin'], own['can_delete']), (True, False, False))
        self.assertFalse(own['comments'][0]['can_delete'])
        own = next(t for t in self.threads(self.author, self.code).data['threads'] if t['id'] == self.own.id)
        self.assertEqual((own['can_resolve'], own['can_pin'], own['can_delete']), (True, True, True))
        self.assertTrue(own['comments'][0]['can_delete'])

    def test_only_course_author_deletes_threads(self):
        self.assertEqual(self.as_user(self.student).delete(f'/api/threads/{self.own.id}/').status_code, 403)
        self.assertEqual(self.as_user(self.author).delete(f'/api/threads/{self.own.id}/').status_code, 204)
        self.assertFalse(Thread.objects.filter(pk=self.own.pk).exists())
        self.assertFalse(Comment.objects.filter(thread_id=self.own.pk).exists())

    def test_only_course_author_deletes_comments(self):
        comment = self.own.comments.last()
        self.assertEqual(self.as_user(self.student).delete(f'/api/comments/{comment.id}/').status_code, 403)
        response = self.as_user(self.author).delete(f'/api/comments/{comment.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_deleted'])
        comment.refresh_from_db()
        self.assertTrue(comment.is_deleted)
        self.assertEqual(comment.deleted_by, self.author)

    def test_deleted_text_goes_to_the_course_author_only(self):
        first = self.own.comments.first()
        self.as_user(self.author).delete(f'/api/comments/{first.id}/')
        for user in (self.student, self.solver):
            with self.subTest(user=user.username):
                thread = next(t for t in self.threads(user, self.code).data['threads'] if t['id'] == self.own.id)
                self.assertEqual(thread['comments'][0]['is_deleted'], True)
                self.assertIsNone(thread['comments'][0]['text'])
                self.assertNotIn('Не понимаю условие', str(self.threads(user, self.code).data))
                self.assertEqual(thread['comments'][1]['text'], 'Перечитай второй абзац')  # the thread stays
        thread = next(t for t in self.threads(self.author, self.code).data['threads'] if t['id'] == self.own.id)
        self.assertEqual(thread['comments'][0]['text'], 'Не понимаю условие')
        self.assertFalse(thread['comments'][0]['can_delete'])


class RateLimitTests(DiscussionTestCase):

    def test_second_post_within_a_minute_is_429(self):
        self.assertEqual(self.reply(self.student, self.own).status_code, 201)
        response = self.start(self.student, self.fill)  # a new thread counts too
        self.assertEqual(response.status_code, 429)
        self.assertIn('раза в минуту', response.data['detail'])
        self.assertTrue(1 <= int(response['Retry-After']) <= 60)
        self.assertFalse(Thread.objects.filter(block=self.fill).exists())

    def test_allowed_again_after_a_minute(self):
        self.reply(self.student, self.own)
        Comment.objects.filter(user=self.student).update(created_at=timezone.now() - timedelta(seconds=61))
        self.assertEqual(self.reply(self.student, self.own).status_code, 201)

    def test_limit_is_per_user(self):
        self.assertEqual(self.reply(self.student, self.own).status_code, 201)
        self.assertEqual(self.reply(self.solver, self.own).status_code, 201)

    def test_course_author_is_exempt(self):
        for _ in range(3):
            self.assertEqual(self.reply(self.author, self.own).status_code, 201)
        self.assertEqual(self.start(self.author, self.fill).status_code, 201)

    def test_rejected_posts_do_not_count(self):
        self.assertEqual(self.reply(self.student, self.own, text='   ').status_code, 400)
        self.assertEqual(self.reply(self.student, self.own).status_code, 201)


class PlainTextTests(DiscussionTestCase):

    def test_empty_and_too_long_text_is_rejected(self):
        for text in ['', '  \n\t ', None]:
            with self.subTest(text=text):
                self.assertEqual(self.start(self.student, self.fill, text).status_code, 400)
        self.assertEqual(self.start(self.student, self.fill, 'я' * (MAX_COMMENT_LENGTH + 1)).status_code, 400)
        self.assertFalse(Thread.objects.filter(block=self.fill).exists())
        self.assertEqual(self.start(self.student, self.fill, 'я' * MAX_COMMENT_LENGTH).status_code, 201)

    def test_html_is_kept_as_text(self):
        text = '<script>alert(1)</script><img src=x onerror="alert(2)"> & <b>жирный</b>'
        response = self.start(self.student, self.fill, f'  {text}\n')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response['Content-Type'], 'application/json')
        # Stored and returned exactly as typed (stripped): not sanitized into
        # something else, not escaped twice; the panel renders it as text.
        self.assertEqual(response.data['comments'][0]['text'], text)
        self.assertEqual(Comment.objects.get(pk=response.data['comments'][0]['id']).text, text)

    @skipUnless(PANEL_SOURCE.exists(), 'no frontend sources (the web image has only the build)')
    def test_panel_never_renders_user_text_as_html(self):
        source = PANEL_SOURCE.read_text('utf-8')
        self.assertNotIn('dangerouslySetInnerHTML', source)
        self.assertNotIn('innerHTML', source)
