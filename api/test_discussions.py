"""
Discussions (api/discussions.py): who may read which threads (the solved-block
rule, enforced on the server), enrolment, who may resolve / pin / delete, the
one-post-a-minute limit, plain text only, and moderation (bans, reports).

Run with: python manage.py test api.test_discussions
"""

from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .discussions import MAX_COMMENT_LENGTH
from .models import (Block, Comment, CommentReport, Course, DiscussionBan, Enrollment, Lesson, Progress, Thread,
                     User)

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

    def test_theory_discussions_are_visible_without_solving(self):
        response = self.start(self.student, self.text)
        self.assertEqual(response.status_code, 201)
        thread_id = response.data['id']
        for user in (self.student, self.classmate, self.author):
            self.assertEqual(self.thread_ids(user, self.text), [thread_id])
            self.assertTrue(self.threads(user, self.text).data['can_see_all'])
            self.assertEqual(self.counts(user).data['counts'][str(self.text.id)], 1)
        reply = self.reply(self.classmate, Thread.objects.get(pk=thread_id), 'Ответ по теории')
        self.assertEqual(reply.status_code, 201)
        for user in (self.outsider, self.other_author):
            self.assertEqual(self.threads(user, self.text).status_code, 404)
            self.assertEqual(self.start(user, self.text).status_code, 404)


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


class BanTests(DiscussionTestCase):

    def ban(self, user, target):
        return self.as_user(user).post('/api/discussions/bans/', {'user_id': target.id}, format='json')

    def test_banned_user_can_read_but_not_post(self):
        self.assertEqual(self.ban(self.author, self.student).status_code, 201)
        response = self.threads(self.student, self.code)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['can_post'])
        for posted in (self.start(self.student, self.fill), self.reply(self.student, self.own)):
            self.assertEqual(posted.status_code, 403)
            self.assertIn('закрыл', posted.data['detail'])
        self.assertEqual(Comment.objects.filter(user=self.student).count(), 1)  # the setup's
        self.assertTrue(self.threads(self.solver, self.code).data['can_post'])  # only her

    def test_unban_lets_them_post_again(self):
        self.ban(self.author, self.student)
        self.assertEqual(self.as_user(self.author).delete(f'/api/discussions/bans/{self.student.id}/').status_code, 204)
        self.assertEqual(self.reply(self.student, self.own).status_code, 201)
        self.assertEqual(self.as_user(self.author).delete(f'/api/discussions/bans/{self.student.id}/').status_code, 404)

    def test_ban_covers_all_her_courses_and_no_one_elses(self):
        second = Course.objects.create(title='SQL', author=self.author)
        second_lesson = Lesson.objects.create(course=second, title='Select', order_index=1)
        second_code = Block.objects.create(lesson=second_lesson, type='CODE', order_index=1, content={'tests': []})
        others = Course.objects.create(title='Go', author=self.other_author)
        others_lesson = Lesson.objects.create(course=others, title='Intro', order_index=1)
        others_code = Block.objects.create(lesson=others_lesson, type='CODE', order_index=1, content={'tests': []})
        for course in (second, others):
            Enrollment.objects.create(student=self.student, course=course)
        self.ban(self.author, self.student)
        self.assertEqual(self.start(self.student, second_code).status_code, 403)
        self.assertEqual(self.start(self.student, others_code).status_code, 201)

    def test_only_a_course_author_bans_her_own_students(self):
        self.assertEqual(self.ban(self.student, self.solver).status_code, 403)       # no courses
        self.assertEqual(self.ban(self.other_author, self.student).status_code, 403)
        Course.objects.create(title='Go', author=self.other_author)
        self.assertEqual(self.ban(self.other_author, self.student).status_code, 404)  # not her student
        self.assertEqual(self.ban(self.author, self.outsider).status_code, 404)
        self.assertEqual(self.ban(self.author, self.author).status_code, 400)
        self.assertEqual(self.as_user(self.author).post('/api/discussions/bans/', {'user_id': 'x'},
                                                        format='json').status_code, 400)
        self.assertFalse(DiscussionBan.objects.exists())

    def test_ban_twice_is_one_ban_and_listed_for_her_only(self):
        self.assertEqual(self.ban(self.author, self.student).status_code, 201)
        self.assertEqual(self.ban(self.author, self.student).status_code, 200)
        bans = self.as_user(self.author).get('/api/discussions/bans/').data['bans']
        self.assertEqual([(b['user_id'], b['username']) for b in bans], [(self.student.id, 'student')])
        self.assertEqual(self.as_user(self.other_author).get('/api/discussions/bans/').data['bans'], [])

    def test_ban_flags_go_to_the_course_author_only(self):
        self.ban(self.author, self.student)
        own = next(t for t in self.threads(self.author, self.code).data['threads'] if t['id'] == self.own.id)
        self.assertEqual((own['comments'][0]['user_is_banned'], own['comments'][0]['can_ban']), (True, True))
        self.assertEqual(own['comments'][1]['user_is_banned'], False)  # solver
        own = next(t for t in self.threads(self.solver, self.code).data['threads'] if t['id'] == self.own.id)
        self.assertEqual((own['comments'][0]['user_is_banned'], own['comments'][0]['can_ban']), (None, False))


class ReportTests(DiscussionTestCase):

    def report(self, user, comment):
        return self.as_user(user).post(f'/api/comments/{comment.id}/report/')

    def reports(self, user):
        return self.as_user(user).get('/api/discussions/reports/').data['reports']

    def test_student_reports_once(self):
        spoiler = self.solvers.comments.first()
        response = self.report(self.student, self.own.comments.last())  # solver's reply in her thread
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['reported'])
        self.assertFalse(response.data['can_report'])
        self.assertIsNone(response.data['report_count'])  # counts are for the course author
        self.assertEqual(self.report(self.student, self.own.comments.last()).status_code, 200)
        self.assertEqual(CommentReport.objects.count(), 1)
        self.assertEqual(self.report(self.solver, spoiler).status_code, 400)  # own comment

    def test_cannot_report_what_one_cannot_read(self):
        spoiler = self.solvers.comments.first()  # student hasn't solved CODE
        self.assertEqual(self.report(self.student, spoiler).status_code, 404)
        self.assertEqual(self.report(self.outsider, spoiler).status_code, 404)
        self.assertFalse(CommentReport.objects.exists())

    def test_course_author_does_not_report_and_is_not_reported(self):
        self.assertEqual(self.report(self.author, self.solvers.comments.first()).status_code, 403)
        hint = make_thread(self.code, self.author, 'Подсказка', pinned=True).comments.first()
        self.assertEqual(self.report(self.student, hint).status_code, 400)
        thread = next(t for t in self.threads(self.student, self.code).data['threads'] if t['starter'] == self.author.id)
        self.assertFalse(thread['comments'][0]['can_report'])
        self.assertFalse(CommentReport.objects.exists())

    def test_deleted_comment_cannot_be_reported(self):
        comment = self.own.comments.last()
        self.as_user(self.author).delete(f'/api/comments/{comment.id}/')
        self.assertEqual(self.report(self.student, comment).status_code, 400)

    def test_author_sees_open_reports_in_her_courses(self):
        spoiler = self.solvers.comments.first()  # seen only by those who solved CODE
        for user in (self.classmate, self.student):
            solve(user, self.code)
            self.assertEqual(self.report(user, spoiler).status_code, 201)
        reports = self.reports(self.author)
        self.assertEqual(len(reports), 1)
        entry = reports[0]
        self.assertEqual((entry['report_count'], entry['comment']['id'], entry['comment']['text']),
                         (2, spoiler.id, 'Моё решение: print(1)'))
        self.assertEqual((entry['block_id'], entry['lesson_title'], entry['course_title']),
                         (str(self.code.id), 'Lists', 'Python basics'))
        self.assertEqual(self.reports(self.other_author), [])
        self.assertEqual(self.reports(self.student), [])
        # In the panel and on the «💬 N» badge too.
        thread = next(t for t in self.threads(self.author, self.code).data['threads'] if t['id'] == self.solvers.id)
        self.assertEqual(thread['comments'][0]['report_count'], 2)
        self.assertEqual(self.counts(self.author).data['reports'], {str(self.code.id): 2})
        self.assertNotIn('reports', self.counts(self.student).data)

    def test_dismissing_or_deleting_closes_reports(self):
        spoiler, reply = self.solvers.comments.first(), self.own.comments.last()
        solve(self.classmate, self.code)
        self.assertEqual(self.report(self.classmate, spoiler).status_code, 201)
        self.assertEqual(self.report(self.student, reply).status_code, 201)
        self.assertEqual(self.as_user(self.student).post(f'/api/comments/{reply.id}/dismiss-reports/').status_code, 403)
        response = self.as_user(self.author).post(f'/api/comments/{reply.id}/dismiss-reports/')
        self.assertEqual((response.status_code, response.data['report_count']), (200, 0))
        self.as_user(self.author).delete(f'/api/comments/{spoiler.id}/')
        self.assertEqual(self.reports(self.author), [])
        self.assertEqual(CommentReport.objects.filter(is_dismissed=True).count(), 1)
        # The reporter still sees that they reported it (no second report).
        self.assertEqual(self.report(self.student, reply).status_code, 200)
