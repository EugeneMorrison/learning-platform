"""
API tests: public registration (always STUDENT), student self-enrolment
(POST /api/enrollments/), the teacher's enroll_student action, and access to
the code runner (/api/run-code/, /api/run-tests/), and the course chat
(POST /api/messages/ and the WebSocket consumer).

Run with: python manage.py test api
"""

import subprocess
from decimal import Decimal
from unittest import mock

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.test import TransactionTestCase
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from .chat import MAX_MESSAGE_LENGTH
from .models import Attempt, Block, Course, Enrollment, Lesson, Message, Progress, User
from .serializers import UserSerializer


class ReadAccessMatrixTests(APITestCase):
    """
    Who can read what (step 4e, Coursera-style; 4f Part 0):
    - course detail: published → everyone; unpublished → its author and its
      enrolled students;
    - lessons and blocks (list and detail): own courses (author) ∪ enrolled
      courses (student); anonymous → nothing. Outside access: list omits it,
      detail is 404.
    """

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.other_author = User.objects.create_user(username='other_author', password='x', role='AUTHOR')
        cls.enrolled = User.objects.create_user(username='enrolled', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        cls.courses = {}
        for kind, published, price in [('free', True, 0), ('paid', True, Decimal('1990')),
                                       ('unpublished', False, 0)]:
            course = Course.objects.create(title=f'{kind} course', author=cls.author,
                                           is_published=published, price=price)
            lesson = Lesson.objects.create(course=course, title=f'{kind} lesson', order_index=1)
            block = Block.objects.create(lesson=lesson, type='TEXT', order_index=1,
                                         content={'html': f'<p>{kind}</p>'})
            # Enrolled in all three (a teacher may enrol students before publishing).
            Enrollment.objects.create(student=cls.enrolled, course=course)
            cls.courses[kind] = (course, lesson, block)

    PERSONAS = ['anonymous', 'outsider', 'enrolled', 'author', 'other_author']

    # persona → kinds of course whose LESSONS/BLOCKS they may read
    CONTENT_ACCESS = {
        'anonymous': set(),
        'outsider': set(),
        'enrolled': {'free', 'paid', 'unpublished'},
        'author': {'free', 'paid', 'unpublished'},
        'other_author': set(),
    }
    # persona → kinds of course whose DETAIL they may read
    COURSE_ACCESS = {
        'anonymous': {'free', 'paid'},
        'outsider': {'free', 'paid'},
        'enrolled': {'free', 'paid', 'unpublished'},  # 4f Part 0
        'author': {'free', 'paid', 'unpublished'},
        'other_author': {'free', 'paid'},
    }

    def login_as(self, persona):
        self.client.force_authenticate(None if persona == 'anonymous' else getattr(self, persona))

    def test_matrix(self):
        for persona in self.PERSONAS:
            self.login_as(persona)
            for kind, (course, lesson, block) in self.courses.items():
                can_read = kind in self.CONTENT_ACCESS[persona]
                with self.subTest(persona=persona, course=kind):
                    lessons = self.client.get(f'/api/lessons/?course={course.id}')
                    self.assertEqual(lessons.status_code, 200)
                    self.assertEqual([l['id'] for l in lessons.data],
                                     [str(lesson.id)] if can_read else [])

                    self.assertEqual(self.client.get(f'/api/lessons/{lesson.id}/').status_code,
                                     200 if can_read else 404)

                    blocks = self.client.get(f'/api/blocks/?lesson={lesson.id}')
                    self.assertEqual(blocks.status_code, 200)
                    self.assertEqual([b['id'] for b in blocks.data],
                                     [str(block.id)] if can_read else [])

                    self.assertEqual(self.client.get(f'/api/blocks/{block.id}/').status_code,
                                     200 if can_read else 404)

                    self.assertEqual(self.client.get(f'/api/courses/{course.id}/').status_code,
                                     200 if kind in self.COURSE_ACCESS[persona] else 404)

    def test_unfiltered_lists_contain_only_accessible_content(self):
        for persona in self.PERSONAS:
            self.login_as(persona)
            expected = {kind for kind in self.courses if kind in self.CONTENT_ACCESS[persona]}
            with self.subTest(persona=persona):
                lesson_ids = {l['id'] for l in self.client.get('/api/lessons/').data}
                block_ids = {b['id'] for b in self.client.get('/api/blocks/').data}
                self.assertEqual(lesson_ids, {str(self.courses[k][1].id) for k in expected})
                self.assertEqual(block_ids, {str(self.courses[k][2].id) for k in expected})

    def test_course_list_unchanged(self):
        self.login_as('anonymous')
        anon = {c['title'] for c in self.client.get('/api/courses/').data}
        self.login_as('author')
        author = {c['title'] for c in self.client.get('/api/courses/').data}

        self.assertEqual(anon, {'free course', 'paid course'})
        self.assertEqual(author, {'free course', 'paid course', 'unpublished course'})

    def test_enrolled_student_sees_unpublished_course_they_are_enrolled_in(self):
        # 4f Part 0: a teacher may enrol students before publishing; they can
        # then open the course (list, detail) and its lessons like any other.
        course, lesson, _ = self.courses['unpublished']
        self.login_as('enrolled')

        titles = [c['title'] for c in self.client.get('/api/courses/').data]
        self.assertEqual(sorted(titles), ['free course', 'paid course', 'unpublished course'])
        self.assertEqual(self.client.get(f'/api/courses/{course.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/lessons/{lesson.id}/').status_code, 200)

    def test_outsider_does_not_see_unpublished_course(self):
        course, _, _ = self.courses['unpublished']
        self.login_as('outsider')

        titles = {c['title'] for c in self.client.get('/api/courses/').data}
        self.assertNotIn('unpublished course', titles)
        self.assertEqual(self.client.get(f'/api/courses/{course.id}/').status_code, 404)

    def test_lesson_404_carries_slug_only_for_published_courses(self):
        self.login_as('anonymous')
        for kind in ['free', 'paid']:
            course, lesson, _ = self.courses[kind]
            response = self.client.get(f'/api/lessons/{lesson.id}/')
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data['course_slug'], course.slug)

        _, unpublished_lesson, _ = self.courses['unpublished']
        for url in [f'/api/lessons/{unpublished_lesson.id}/',
                    '/api/lessons/3fa85f64-5717-4562-b3fc-2c963f66afa6/',
                    '/api/lessons/not-a-uuid/']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)
            self.assertNotIn('course_slug', response.data, url)

    def test_writes_unchanged_for_other_authors(self):
        # Other author: lessons/blocks of someone else's course are still not found for writes.
        self.login_as('other_author')
        _, lesson, block = self.courses['free']

        self.assertEqual(self.client.patch(f'/api/lessons/{lesson.id}/', {'title': 'Hacked'},
                                           format='json').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/blocks/{block.id}/').status_code, 404)
        lesson.refresh_from_db()
        self.assertEqual(lesson.title, 'free lesson')

    def test_author_can_still_edit_own_content(self):
        self.login_as('author')
        _, lesson, block = self.courses['unpublished']

        self.assertEqual(self.client.patch(f'/api/lessons/{lesson.id}/', {'title': 'Renamed'},
                                           format='json').status_code, 200)
        self.assertEqual(self.client.patch(f'/api/blocks/{block.id}/', {'order_index': 2},
                                           format='json').status_code, 200)

    def test_own_progress_page_needs_content_access(self):
        course, _, _ = self.courses['free']
        for persona, expected in [('outsider', 404), ('enrolled', 200)]:
            self.login_as(persona)
            user = getattr(self, persona)
            response = self.client.get(f'/api/progress/student/{user.id}/course/{course.id}/')
            self.assertEqual(response.status_code, expected, persona)


class RenameTests(APITestCase):
    """PATCH {"title"} on a course / lesson: owner only, validated, URL-neutral."""

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.other = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Python', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Variables', order_index=1)

    def rename(self, user, kind, obj, title):
        self.client.force_authenticate(user)
        return self.client.patch(f'/api/{kind}/{obj.id}/', {'title': title}, format='json')

    def test_owner_renames_course_and_slug_stays(self):
        slug = self.course.slug
        response = self.rename(self.author, 'courses', self.course, '  Новое название  ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'Новое название')
        self.course.refresh_from_db()
        self.assertEqual(self.course.slug, slug)

    def test_owner_renames_lesson(self):
        response = self.rename(self.author, 'lessons', self.lesson, 'Типы данных')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'Типы данных')

    def test_others_cannot_rename(self):
        self.assertEqual(self.rename(self.other, 'courses', self.course, 'X1').status_code, 403)
        self.assertEqual(self.rename(self.student, 'courses', self.course, 'X1').status_code, 403)
        self.assertEqual(self.rename(self.other, 'lessons', self.lesson, 'X1').status_code, 404)
        self.assertEqual(self.rename(self.student, 'lessons', self.lesson, 'X1').status_code, 403)
        self.course.refresh_from_db()
        self.lesson.refresh_from_db()
        self.assertEqual((self.course.title, self.lesson.title), ('Python', 'Variables'))

    def test_empty_and_too_long_titles_are_rejected_in_russian(self):
        for kind, obj in [('courses', self.course), ('lessons', self.lesson)]:
            for title in ['', '   ', 'x' * 256]:
                response = self.rename(self.author, kind, obj, title)
                self.assertEqual(response.status_code, 400, (kind, title))
                self.assertRegex(response.data['title'][0], '[А-Яа-я]')
            self.assertEqual(self.rename(self.author, kind, obj, 'y' * 255).status_code, 200)


class LessonNavigationTests(APITestCase):
    """GET /api/lessons/{id}/ carries course_title and next_lesson_id (the next
    lesson of the same course by order_index; null on the last lesson)."""

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Строки', author=cls.author, is_published=True)
        # Created out of order and with gaps: the order comes from order_index.
        cls.last = Lesson.objects.create(course=cls.course, title='Last', order_index=7)
        cls.first = Lesson.objects.create(course=cls.course, title='First', order_index=1)
        cls.middle = Lesson.objects.create(course=cls.course, title='Middle', order_index=3)
        # Another course's lesson sits between them by order_index; never "next".
        other = Course.objects.create(title='Other', author=cls.author, is_published=True)
        Lesson.objects.create(course=other, title='Elsewhere', order_index=2)
        Enrollment.objects.create(student=cls.student, course=cls.course)

    def get_lesson(self, lesson):
        self.client.force_authenticate(self.student)
        response = self.client.get(f'/api/lessons/{lesson.id}/')
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_next_lesson_follows_order_index_within_the_course(self):
        self.assertEqual(str(self.get_lesson(self.first)['next_lesson_id']), str(self.middle.id))
        self.assertEqual(str(self.get_lesson(self.middle)['next_lesson_id']), str(self.last.id))

    def test_last_lesson_has_no_next(self):
        self.assertIsNone(self.get_lesson(self.last)['next_lesson_id'])

    def test_course_title_is_included(self):
        self.assertEqual(self.get_lesson(self.middle)['course_title'], 'Строки')

    def test_course_completed_only_when_every_task_is_solved(self):
        # "Курс пройден" on the last lesson only then; until then "Последний урок".
        quiz = Block.objects.create(lesson=self.first, type='QUIZ', order_index=1, content={
            'question': 'q', 'options': ['a', 'b'], 'correct_answer': 1})
        code = Block.objects.create(lesson=self.last, type='CODE', order_index=1, content={
            'prompt': 'p', 'starter_code': '', 'tests': [{'input': '', 'expected': '1'}]})
        Block.objects.create(lesson=self.last, type='TEXT', order_index=2, content={'html': 't'})
        Progress.objects.create(student=self.student, lesson=self.first, block=quiz,
                                answer={'selected': 1}, is_correct=True)
        wrong = Progress.objects.create(student=self.student, lesson=self.last, block=code,
                                        answer={'code': 'print(2)'}, is_correct=False)
        self.assertFalse(self.get_lesson(self.last)['course_completed'])

        wrong.is_correct = True
        wrong.save()
        # The TEXT block has no progress and doesn't count.
        self.assertTrue(self.get_lesson(self.last)['course_completed'])

    def test_next_lesson_id_is_read_only(self):
        self.client.force_authenticate(self.author)
        response = self.client.patch(f'/api/lessons/{self.first.id}/',
                                     {'next_lesson_id': str(self.last.id)}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(self.get_lesson(self.first)['next_lesson_id']), str(self.middle.id))

    def test_lesson_title_is_still_validated(self):
        # Guards LessonSerializer.validate_title (it once ended up on a subclass).
        self.client.force_authenticate(self.author)
        for title in ['   ', 'x']:
            response = self.client.patch(f'/api/lessons/{self.first.id}/', {'title': title}, format='json')
            self.assertEqual(response.status_code, 400, title)
            self.assertIn('title', response.data)
        self.first.refresh_from_db()
        self.assertEqual(self.first.title, 'First')

    def test_lesson_position_and_count_ignore_order_index_gaps(self):
        # order_index 1, 3, 7 → "Урок 1/2/3 из 3".
        for lesson, position in [(self.first, 1), (self.middle, 2), (self.last, 3)]:
            data = self.get_lesson(lesson)
            self.assertEqual((data['lesson_position'], data['lesson_count']), (position, 3), lesson.title)


class LessonOutlineTests(APITestCase):
    """GET /api/lessons/outline/?course=<id>: the lessons panel. Positions agree
    with the single lesson's lesson_position; counts follow the viewer's rule
    (QUIZ/CODE/FILL tasks, solved = is_correct); only the caller's own progress."""

    URL = '/api/lessons/outline/'

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.classmate = User.objects.create_user(username='classmate', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        # Gaps in order_index, created out of order.
        cls.l3 = Lesson.objects.create(course=cls.course, title='Third', order_index=10)
        cls.l1 = Lesson.objects.create(course=cls.course, title='First', order_index=2)
        cls.l2 = Lesson.objects.create(course=cls.course, title='Theory only', order_index=5)
        for user in (cls.student, cls.classmate):
            Enrollment.objects.create(student=user, course=cls.course)

        def block(lesson, type_, order):
            return Block.objects.create(lesson=lesson, type=type_, order_index=order, content={})

        quiz, code, fill = block(cls.l1, 'QUIZ', 1), block(cls.l1, 'CODE', 2), block(cls.l1, 'FILL', 3)
        text1 = block(cls.l1, 'TEXT', 4)
        block(cls.l2, 'TEXT', 1)
        last_quiz = block(cls.l3, 'QUIZ', 1)

        def progress(user, b, correct):
            Progress.objects.create(student=user, lesson=b.lesson, block=b, answer={}, is_correct=correct)

        # student: quiz + fill right, code wrong, TEXT "completed" (never a task).
        progress(cls.student, quiz, True)
        progress(cls.student, code, False)
        progress(cls.student, fill, True)
        progress(cls.student, text1, True)
        # classmate solved everything; must not leak into the student's counts.
        for b in (quiz, code, fill, last_quiz):
            progress(cls.classmate, b, True)

    def outline(self, user, course_id=None):
        self.client.force_authenticate(user)
        return self.client.get(self.URL, {'course': str(course_id or self.course.id)})

    def rows(self, user):
        response = self.outline(user)
        self.assertEqual(response.status_code, 200)
        return {row['title']: row for row in response.data}

    def test_positions_agree_with_single_lesson_including_gaps(self):
        data = self.outline(self.student).data
        self.assertEqual([row['title'] for row in data], ['First', 'Theory only', 'Third'])
        self.assertEqual([row['position'] for row in data], [1, 2, 3])
        for row in data:
            lesson = self.client.get(f"/api/lessons/{row['id']}/").data
            self.assertEqual(lesson['lesson_position'], row['position'], row['title'])
            self.assertEqual(lesson['lesson_count'], len(data))

    def test_counts_follow_the_viewer_rule(self):
        rows = self.rows(self.student)
        self.assertEqual((rows['First']['task_count'], rows['First']['solved_count']), (3, 2))
        self.assertEqual((rows['Theory only']['task_count'], rows['Theory only']['solved_count']), (0, 0))
        self.assertEqual((rows['Third']['task_count'], rows['Third']['solved_count']), (1, 0))

    def test_counts_match_what_the_viewer_computes(self):
        # The viewer: tasks from /api/blocks/?lesson=, solved from /api/progress/course/.
        self.client.force_authenticate(self.student)
        progress = self.client.get(f'/api/progress/course/{self.course.id}/').data
        solved_ids = {str(p['block']) for p in progress if p['is_correct'] is True}
        for row in self.outline(self.student).data:
            blocks = self.client.get('/api/blocks/', {'lesson': str(row['id'])}).data
            tasks = [b for b in blocks if b['type'] in ('QUIZ', 'CODE', 'FILL')]
            self.assertEqual(row['task_count'], len(tasks), row['title'])
            self.assertEqual(row['solved_count'], sum(str(b['id']) in solved_ids for b in tasks), row['title'])

    def test_only_the_callers_own_progress(self):
        self.assertEqual(self.rows(self.classmate)['First']['solved_count'], 3)
        self.assertEqual(self.rows(self.student)['First']['solved_count'], 2)
        # No way to ask for someone else's: extra parameters are ignored.
        self.client.force_authenticate(self.student)
        response = self.client.get(self.URL, {'course': str(self.course.id), 'student': self.classmate.id})
        self.assertEqual({r['title']: r['solved_count'] for r in response.data}['First'], 2)

    def test_author_gets_lessons_without_progress(self):
        rows = self.rows(self.author)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row['solved_count'] is None for row in rows.values()))
        self.assertEqual(rows['First']['task_count'], 3)

    def test_access(self):
        self.assertEqual(self.outline(self.outsider).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.URL, {'course': str(self.course.id)}).status_code, 401)
        self.assertEqual(self.outline(self.student, course_id='not-a-uuid').status_code, 400)


class BlockDuplicateTests(APITestCase):
    """POST /api/blocks/{id}/duplicate/: the lesson editor's "Копировать"."""

    CONTENT = {
        'TEXT': {'html': '<p>Теория</p><img src="/media/lesson_images/a.png">'},
        'QUIZ': {'question': 'q', 'options': ['a', 'b'], 'correct_answer': 1, 'explanation': 'e'},
        'CODE': {'prompt': 'p', 'starter_code': '# код\n', 'solution': 'print(1)',
                 'tests': [{'input': '1\n2', 'expected': '3', 'visible': True},
                           {'input': '5\n5', 'expected': '10', 'visible': False}]},
        'FILL': {'prompt': 'p', 'template': 'print({{8}})', 'explanation': 'e'},
    }

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.other_author = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Lesson', order_index=1)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        # One block of each type, order_index 1..4.
        cls.blocks = [
            Block.objects.create(lesson=cls.lesson, type=type_, order_index=i, content=cls.CONTENT[type_])
            for i, type_ in enumerate(['TEXT', 'QUIZ', 'CODE', 'FILL'], start=1)
        ]

    def duplicate(self, block, user=None):
        self.client.force_authenticate(user or self.author)
        return self.client.post(f'/api/blocks/{block.id}/duplicate/')

    def lesson_order(self, lesson=None):
        """[(id, order_index)] of the lesson's blocks in order."""
        return list(Block.objects.filter(lesson=lesson or self.lesson)
                    .order_by('order_index').values_list('id', 'order_index'))

    def test_copy_in_the_middle_goes_right_below(self):
        text, quiz, code, fill = self.blocks
        response = self.duplicate(quiz)
        self.assertEqual(response.status_code, 201)
        new_id = response.data['id']
        self.assertEqual([str(i) for i, _ in self.lesson_order()],
                         [str(b.id) for b in (text, quiz)] + [str(new_id)] + [str(b.id) for b in (code, fill)])
        # Blocks below moved down by one; those above didn't move.
        self.assertEqual([o for _, o in self.lesson_order()], [1, 2, 3, 4, 5])
        self.assertEqual(response.data['order_index'], 3)

    def test_copy_of_the_last_block(self):
        fill = self.blocks[-1]
        response = self.duplicate(fill)
        self.assertEqual(response.status_code, 201)
        order = self.lesson_order()
        self.assertEqual(str(order[-1][0]), str(response.data['id']))
        self.assertEqual([o for _, o in order], [1, 2, 3, 4, 5])

    def test_gaps_in_order_index(self):
        lesson = Lesson.objects.create(course=self.course, title='Gaps', order_index=2)
        a = Block.objects.create(lesson=lesson, type='TEXT', order_index=0, content={'html': 'a'})
        b = Block.objects.create(lesson=lesson, type='TEXT', order_index=5, content={'html': 'b'})
        c = Block.objects.create(lesson=lesson, type='TEXT', order_index=6, content={'html': 'c'})
        d = Block.objects.create(lesson=lesson, type='TEXT', order_index=20, content={'html': 'd'})
        new_id = self.duplicate(b).data['id']
        order = self.lesson_order(lesson)
        self.assertEqual([str(i) for i, _ in order], [str(x) for x in (a.id, b.id, new_id, c.id, d.id)])
        # Gaps above stay; only blocks below moved, by one.
        self.assertEqual([o for _, o in order], [0, 5, 6, 7, 21])

    def test_copies_of_all_types_pass_validation_and_keep_content(self):
        for block in self.blocks:
            response = self.duplicate(block)
            self.assertEqual(response.status_code, 201, block.type)
            self.assertEqual(response.data['type'], block.type)
            self.assertNotEqual(str(response.data['id']), str(block.id))
            # The author's view: full content, hidden tests and solution included.
            self.assertEqual(response.data['content'], self.CONTENT[block.type], block.type)
        # TEXT: the image URL is kept as is.
        text_copy = Block.objects.filter(lesson=self.lesson, type='TEXT').exclude(pk=self.blocks[0].pk).get()
        self.assertIn('/media/lesson_images/a.png', text_copy.content['html'])

    def test_content_is_a_deep_copy(self):
        code = self.blocks[2]
        new_id = self.duplicate(code).data['id']
        copy_ = Block.objects.get(pk=new_id)
        copy_.content['tests'][0]['expected'] = 'changed'
        copy_.content['prompt'] = 'changed'
        copy_.save()
        code.refresh_from_db()
        self.assertEqual(code.content, self.CONTENT['CODE'])

    def test_invalid_original_is_refused_and_nothing_moves(self):
        # Same validation as the editor: a FILL without a blank can't be copied,
        # and the shift is rolled back.
        broken = self.blocks[1]
        Block.objects.filter(pk=broken.pk).update(type='FILL', content={'template': 'no blanks'})
        before = self.lesson_order()
        self.assertEqual(self.duplicate(broken).status_code, 400)
        self.assertEqual(self.lesson_order(), before)

    def test_no_progress_or_attempts_are_copied(self):
        quiz = self.blocks[1]
        Progress.objects.create(student=self.student, lesson=self.lesson, block=quiz,
                                answer={'selected': 1}, is_correct=True)
        Attempt.objects.create(student=self.student, block=quiz, answer={'selected': 1}, is_correct=True)
        new_id = self.duplicate(quiz).data['id']
        self.assertFalse(Progress.objects.filter(block_id=new_id).exists())
        self.assertFalse(Attempt.objects.filter(block_id=new_id).exists())
        self.assertEqual(Progress.objects.filter(block=quiz).count(), 1)
        self.assertEqual(Attempt.objects.filter(block=quiz).count(), 1)

    def test_access(self):
        quiz = self.blocks[1]
        before = self.lesson_order()
        self.assertEqual(self.duplicate(quiz, self.student).status_code, 403)
        # Another author: 404, the same as PATCH/DELETE on that block.
        self.client.force_authenticate(self.other_author)
        self.assertEqual(self.client.patch(f'/api/blocks/{quiz.id}/', {'order_index': 9}).status_code, 404)
        self.assertEqual(self.duplicate(quiz, self.other_author).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'/api/blocks/{quiz.id}/duplicate/').status_code, 401)
        self.assertEqual(self.lesson_order(), before)


class ParentOwnershipTests(APITestCase):
    """Lessons and blocks may only be created in, or moved into, the requesting
    author's own course / lesson (403 otherwise). The owner is unaffected."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username='owner', password='x', role='AUTHOR')
        cls.other = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.course = Course.objects.create(title='Owner course', author=cls.owner)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Owner lesson', order_index=1)
        cls.course2 = Course.objects.create(title='Owner course 2', author=cls.owner)
        cls.lesson2 = Lesson.objects.create(course=cls.course2, title='Owner lesson 2', order_index=1)
        cls.other_course = Course.objects.create(title='Other course', author=cls.other)
        cls.other_lesson = Lesson.objects.create(course=cls.other_course, title='Other lesson', order_index=1)
        cls.other_block = Block.objects.create(lesson=cls.other_lesson, type='TEXT', order_index=1,
                                               content={'html': '<p>other</p>'})
        cls.block = Block.objects.create(lesson=cls.lesson, type='TEXT', order_index=1,
                                         content={'html': '<p>mine</p>'})

    def as_(self, user):
        self.client.force_authenticate(user)
        return self.client

    # --- creating in someone else's course / lesson ------------------------

    def test_other_author_cannot_create_a_lesson_in_my_course(self):
        response = self.as_(self.other).post('/api/lessons/', {
            'course': str(self.course.id), 'title': 'Injected', 'order_index': 5}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Lesson.objects.filter(title='Injected').exists())

    def test_other_author_cannot_create_a_block_in_my_lesson(self):
        response = self.as_(self.other).post('/api/blocks/', {
            'lesson': str(self.lesson.id), 'type': 'TEXT', 'order_index': 9,
            'content': {'html': '<p>injected</p>'}}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.lesson.blocks.count(), 1)

    # --- moving into someone else's course / lesson ------------------------

    def test_other_author_cannot_move_their_block_into_my_lesson(self):
        for method in ('patch', 'put'):
            body = {'lesson': str(self.lesson.id), 'order_index': 50}
            if method == 'put':
                body.update(type='TEXT', content={'html': '<p>other</p>'})
            response = getattr(self.as_(self.other), method)(
                f'/api/blocks/{self.other_block.id}/', body, format='json')
            self.assertEqual(response.status_code, 403, method)
            self.other_block.refresh_from_db()
            self.assertEqual(self.other_block.lesson_id, self.other_lesson.id, method)

    def test_other_author_cannot_move_their_lesson_into_my_course(self):
        other_lesson2 = Lesson.objects.create(course=self.other_course, title='Other 2', order_index=2)
        response = self.as_(self.other).patch(f'/api/lessons/{other_lesson2.id}/', {
            'course': str(self.course.id), 'order_index': 60}, format='json')
        self.assertEqual(response.status_code, 403)
        other_lesson2.refresh_from_db()
        self.assertEqual(other_lesson2.course_id, self.other_course.id)

    def test_owner_cannot_move_into_someone_elses_lesson_or_course_either(self):
        response = self.as_(self.owner).patch(f'/api/blocks/{self.block.id}/', {
            'lesson': str(self.other_lesson.id), 'order_index': 70}, format='json')
        self.assertEqual(response.status_code, 403)
        response = self.as_(self.owner).patch(f'/api/lessons/{self.lesson2.id}/', {
            'course': str(self.other_course.id), 'order_index': 70}, format='json')
        self.assertEqual(response.status_code, 403)

    # --- the owner still can -------------------------------------------------

    def test_owner_creates_and_moves_within_own_courses(self):
        client = self.as_(self.owner)
        response = client.post('/api/lessons/', {
            'course': str(self.course.id), 'title': 'New lesson', 'order_index': 2}, format='json')
        self.assertEqual(response.status_code, 201)
        response = client.post('/api/blocks/', {
            'lesson': str(self.lesson.id), 'type': 'QUIZ', 'order_index': 2,
            'content': {'question': 'q', 'options': ['a', 'b'], 'correct_answer': 0}}, format='json')
        self.assertEqual(response.status_code, 201)
        # Move a block to another lesson, and a lesson to another course, both owned.
        response = client.patch(f'/api/blocks/{self.block.id}/', {
            'lesson': str(self.lesson2.id), 'order_index': 5}, format='json')
        self.assertEqual(response.status_code, 200)
        response = client.patch(f'/api/lessons/{self.lesson2.id}/', {
            'course': str(self.course.id), 'order_index': 3}, format='json')
        self.assertEqual(response.status_code, 200)
        # The editor's save (PUT with its own lesson) and up/down (PATCH order_index).
        response = client.put(f'/api/blocks/{self.block.id}/', {
            'lesson': str(self.lesson2.id), 'type': 'TEXT', 'order_index': 6,
            'content': {'html': '<p>edited</p>'}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.patch(f'/api/blocks/{self.block.id}/', {'order_index': 7},
                                      format='json').status_code, 200)

    def test_unknown_parent_is_still_a_400(self):
        response = self.as_(self.owner).post('/api/blocks/', {
            'lesson': '3fa85f64-5717-4562-b3fc-2c963f66afa6', 'type': 'TEXT', 'order_index': 3,
            'content': {'html': 'x'}}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('lesson', response.data)


class BlockContentValidationOnPatchTests(APITestCase):
    """PATCH without "type" is validated against the block's stored type; a
    PATCH of "type" alone checks the stored content."""

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=course, title='Lesson', order_index=1)
        Enrollment.objects.create(student=cls.student, course=course)
        cls.quiz_content = {'question': 'q', 'options': ['a', 'b'], 'correct_answer': 1}
        cls.quiz = Block.objects.create(lesson=cls.lesson, type='QUIZ', order_index=1, content=cls.quiz_content)

    def patch(self, body):
        self.client.force_authenticate(self.author)
        return self.client.patch(f'/api/blocks/{self.quiz.id}/', body, format='json')

    def test_patch_without_type_and_invalid_content_is_400(self):
        for content in ({}, {'question': 'q'}, 'just a string', ['a', 'list']):
            response = self.patch({'content': content})
            self.assertEqual(response.status_code, 400, content)
            self.assertIn('content', response.data)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.content, self.quiz_content)
        # The lesson still loads for students.
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get('/api/blocks/', {'lesson': str(self.lesson.id)}).status_code, 200)

    def test_patch_of_type_alone_checks_the_stored_content(self):
        response = self.patch({'type': 'CODE'})
        self.assertEqual(response.status_code, 400)
        self.quiz.refresh_from_db()
        self.assertEqual(self.quiz.type, 'QUIZ')

    def test_valid_patches_still_work(self):
        response = self.patch({'content': dict(self.quiz_content, question='new')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.patch({'order_index': 4}).status_code, 200)
        response = self.patch({'type': 'TEXT', 'content': {'html': '<p>now theory</p>'}})
        self.assertEqual(response.status_code, 200)


class LessonReorderTests(APITestCase):
    """POST /api/lessons/{id}/reorder/ {"new_order": N}: N is a 1-based
    position in the course's lesson list; the course page's ↑ / ↓."""

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.other = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        # Gaps in order_index, created out of order.
        cls.c = Lesson.objects.create(course=cls.course, title='C', order_index=7)
        cls.a = Lesson.objects.create(course=cls.course, title='A', order_index=1)
        cls.d = Lesson.objects.create(course=cls.course, title='D', order_index=20)
        cls.b = Lesson.objects.create(course=cls.course, title='B', order_index=3)
        # Another course with a lesson at the same order_index values: untouched.
        other_course = Course.objects.create(title='Other', author=cls.author)
        cls.elsewhere = Lesson.objects.create(course=other_course, title='X', order_index=3)
        Enrollment.objects.create(student=cls.student, course=cls.course)

    def reorder(self, lesson, new_order, user=None, **extra):
        self.client.force_authenticate(user or self.author)
        body = {} if new_order is ... else {'new_order': new_order}
        return self.client.post(f'/api/lessons/{lesson.id}/reorder/', body, format='json', **extra)

    def titles(self):
        return list(Lesson.objects.filter(course=self.course).order_by('order_index')
                    .values_list('title', flat=True))

    def test_move_up(self):
        response = self.reorder(self.c, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.titles(), ['C', 'A', 'B', 'D'])
        # The response is the course's list in the new order.
        self.assertEqual([l['title'] for l in response.data], ['C', 'A', 'B', 'D'])

    def test_move_down(self):
        response = self.reorder(self.a, 3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.titles(), ['B', 'C', 'A', 'D'])

    def test_gaps_keep_the_same_order_index_values(self):
        self.reorder(self.b, 4)
        values = list(Lesson.objects.filter(course=self.course).order_by('order_index')
                      .values_list('title', 'order_index'))
        self.assertEqual(values, [('A', 1), ('C', 3), ('D', 7), ('B', 20)])
        self.elsewhere.refresh_from_db()
        self.assertEqual(self.elsewhere.order_index, 3)

    def test_first_up_is_rejected_and_last_down_stays(self):
        # The UI disables these; the API: below 1 → 400, past the end → clamped.
        self.assertEqual(self.reorder(self.a, 0).status_code, 400)
        response = self.reorder(self.d, 5)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.titles(), ['A', 'B', 'C', 'D'])
        self.assertEqual(self.reorder(self.a, 99).status_code, 200)
        self.assertEqual(self.titles(), ['B', 'C', 'D', 'A'])

    def test_same_place_changes_nothing(self):
        response = self.reorder(self.b, 2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.titles(), ['A', 'B', 'C', 'D'])

    def test_new_order_must_be_an_integer(self):
        for value in ('abc', '', 2.5, True, None, [2], {'n': 2}, ...):
            with self.subTest(value=value):
                self.assertEqual(self.reorder(self.b, value).status_code, 400)
        self.assertEqual(self.titles(), ['A', 'B', 'C', 'D'])
        # A numeric string is fine (forms send strings).
        self.assertEqual(self.reorder(self.b, '3').status_code, 200)
        self.assertEqual(self.titles(), ['A', 'C', 'B', 'D'])

    def test_access(self):
        self.assertEqual(self.reorder(self.b, 1, user=self.student).status_code, 403)
        self.assertEqual(self.reorder(self.b, 1, user=self.other).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f'/api/lessons/{self.b.id}/reorder/', {'new_order': 1},
                                          format='json').status_code, 401)
        self.assertEqual(self.titles(), ['A', 'B', 'C', 'D'])

    def test_navigation_and_outline_follow_the_new_order(self):
        self.reorder(self.d, 1)  # D, A, B, C
        self.client.force_authenticate(self.student)
        d = self.client.get(f'/api/lessons/{self.d.id}/').data
        self.assertEqual((d['lesson_position'], str(d['next_lesson_id'])), (1, str(self.a.id)))
        c = self.client.get(f'/api/lessons/{self.c.id}/').data
        self.assertEqual((c['lesson_position'], c['next_lesson_id']), (4, None))
        outline = self.client.get('/api/lessons/outline/', {'course': str(self.course.id)}).data
        self.assertEqual([(r['title'], r['position']) for r in outline],
                         [('D', 1), ('A', 2), ('B', 3), ('C', 4)])


class ProgressSubmitAccessTests(APITestCase):
    SUBMIT_URL = '/api/progress/submit/'

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.enrolled = User.objects.create_user(username='enrolled', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        lesson = Lesson.objects.create(course=course, title='Lesson', order_index=1)
        cls.quiz = Block.objects.create(lesson=lesson, type='QUIZ', order_index=1, content={
            'question': 'q', 'options': ['a', 'b'], 'correct_answer': 1})
        Enrollment.objects.create(student=cls.enrolled, course=course)

    def submit(self, user, block_id, answer=None):
        self.client.force_authenticate(user)
        body = {'answer': answer or {'selected': 1}}
        if block_id is not None:
            body['block'] = str(block_id)
        return self.client.post(self.SUBMIT_URL, body, format='json')

    def test_anonymous_gets_401(self):
        self.assertEqual(self.submit(None, self.quiz.id).status_code, 401)
        self.assertFalse(Progress.objects.exists())

    def test_missing_block_gets_400(self):
        self.assertEqual(self.submit(self.enrolled, None).status_code, 400)

    def test_unknown_block_gets_404(self):
        for block_id in ['3fa85f64-5717-4562-b3fc-2c963f66afa6', 'not-a-uuid']:
            self.assertEqual(self.submit(self.enrolled, block_id).status_code, 404, block_id)
        self.assertFalse(Progress.objects.exists())

    def test_not_enrolled_gets_403(self):
        response = self.submit(self.outsider, self.quiz.id)

        self.assertEqual(response.status_code, 403)
        self.assertIn('detail', response.data)
        self.assertFalse(Progress.objects.exists())

    def test_enrolled_student_submits_and_is_graded(self):
        response = self.submit(self.enrolled, self.quiz.id, {'selected': 1})

        self.assertEqual(response.status_code, 200)
        progress = Progress.objects.get(student=self.enrolled, block=self.quiz)
        self.assertTrue(progress.is_correct)

    def test_course_author_can_submit(self):
        self.assertEqual(self.submit(self.author, self.quiz.id).status_code, 200)

    def test_removed_progress_viewset_routes_do_not_write(self):
        own = Progress.objects.create(student=self.outsider, block=self.quiz, lesson=self.quiz.lesson,
                                      completed=False, is_correct=False)
        self.client.force_authenticate(self.outsider)
        body = {'block': str(self.quiz.id), 'lesson': str(self.quiz.lesson_id),
                'completed': True, 'is_correct': True}

        attempts = [
            self.client.post('/api/progress/', body, format='json'),
            self.client.post('/api/progress.json', body, format='json'),
            self.client.put(f'/api/progress/{own.id}/', body, format='json'),
            self.client.patch(f'/api/progress/{own.id}/', {'is_correct': True}, format='json'),
            self.client.post('/api/progress/submit.json', body, format='json'),
        ]

        for response in attempts:
            self.assertEqual(response.status_code, 404, response.request['PATH_INFO'])
        own.refresh_from_db()
        self.assertFalse(own.is_correct)
        self.assertEqual(Progress.objects.count(), 1)

REGISTER_URL = '/api/auth/register/'
RUN_CODE_URL = '/api/run-code/'
RUN_TESTS_URL = '/api/run-tests/'


def fake_run(stdout='2\n', returncode=0, stderr=''):
    """Stand-in for runner.run_python: these tests never start an interpreter
    (RunnerLockdownTests below do)."""
    return mock.patch(
        'api.views.run_python',
        return_value=subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr),
    )


def fake_program(outputs, errors=None):
    """run_python stand-in that answers by stdin: outputs[stdin] is printed;
    stdin in `errors` exits with that stderr. Unknown stdin prints nothing."""
    errors = errors or {}

    def run(code, stdin='', version='', header='', footer=''):
        if stdin in errors:
            return subprocess.CompletedProcess([], 1, stdout='', stderr=errors[stdin])
        return subprocess.CompletedProcess([], 0, stdout=outputs.get(stdin, '') + '\n', stderr='')

    return mock.patch('api.views.run_python', side_effect=run)


class StudentContentAndGradingTests(APITestCase):
    """Step 4f: students never receive answers; all grading on the server."""

    # Markers planted in every answer-bearing field.
    SOLUTION = 'MARK-SOLUTION'
    HIDDEN_IN = 'MARK-HIDDEN-IN'
    HIDDEN_OUT = 'MARK-HIDDEN-OUT'
    QUIZ_EXPL = 'MARK-QUIZ-EXPLANATION'
    FILL_ANSWER = 'MARK-FILL-ANSWER'
    FILL_ALT = 'mark-fill-alt'
    FILL_EXPL = 'MARK-FILL-EXPLANATION'
    HEADER = '# MARK-HEADER'
    FOOTER = '# MARK-FOOTER'
    ALL_MARKERS = [SOLUTION, HIDDEN_IN, HIDDEN_OUT, QUIZ_EXPL, FILL_ANSWER, FILL_ALT, FILL_EXPL,
                   HEADER, FOOTER]

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Lesson', order_index=1)
        # No visible flags → default rule: first 2 visible, the 3rd hidden.
        cls.code = Block.objects.create(lesson=cls.lesson, type='CODE', order_index=1, content={
            'prompt': 'p', 'starter_code': '', 'solution': cls.SOLUTION,
            'header': cls.HEADER, 'footer': cls.FOOTER,
            'tests': [{'input': 'in1', 'expected': 'out1'},
                      {'input': 'in2', 'expected': 'out2'},
                      {'input': cls.HIDDEN_IN, 'expected': cls.HIDDEN_OUT}]})
        cls.quiz = Block.objects.create(lesson=cls.lesson, type='QUIZ', order_index=2, content={
            'question': 'q', 'options': ['a', 'b', 'c'], 'correct_answer': 2,
            'explanation': cls.QUIZ_EXPL})
        cls.fill = Block.objects.create(lesson=cls.lesson, type='FILL', order_index=3, content={
            'prompt': 'p', 'template': f'x = {{{{{cls.FILL_ANSWER}|{cls.FILL_ALT}}}}}\nprint({{{{x}}}})',
            'case_sensitive': False, 'explanation': cls.FILL_EXPL})
        Enrollment.objects.create(student=cls.student, course=cls.course)

    def setUp(self):
        cache.clear()  # runner throttle counters

    def as_user(self, user):
        self.client.force_authenticate(user)

    # --- what students and authors receive ---------------------------------

    def block_responses(self):
        yield self.client.get(f'/api/blocks/?lesson={self.lesson.id}')
        for block in [self.code, self.quiz, self.fill]:
            yield self.client.get(f'/api/blocks/{block.id}/')

    def test_student_never_receives_answer_markers(self):
        self.as_user(self.student)
        for response in self.block_responses():
            self.assertEqual(response.status_code, 200)
            body = response.content.decode()
            for marker in self.ALL_MARKERS:
                self.assertNotIn(marker, body, response.request['PATH_INFO'])

        by_type = {b['type']: b['content'] for b in
                   self.client.get(f'/api/blocks/?lesson={self.lesson.id}').data}
        for field in ['solution', 'header', 'footer']:
            self.assertNotIn(field, by_type['CODE'])
        self.assertNotIn('correct_answer', by_type['QUIZ'])
        self.assertNotIn('explanation', by_type['QUIZ'])
        self.assertNotIn('explanation', by_type['FILL'])
        # FILL: same gaps, no answers.
        self.assertEqual(by_type['FILL']['template'], 'x = {{}}\nprint({{}})')

    def test_author_receives_full_content(self):
        self.as_user(self.author)
        body = ''.join(r.content.decode() for r in self.block_responses())
        for marker in self.ALL_MARKERS:
            self.assertIn(marker, body)
        quiz = self.client.get(f'/api/blocks/{self.quiz.id}/').data['content']
        self.assertEqual(quiz['correct_answer'], 2)
        code = self.client.get(f'/api/blocks/{self.code.id}/').data['content']
        self.assertEqual((code['header'], code['footer']), (self.HEADER, self.FOOTER))

    def test_default_rule_first_two_tests_visible(self):
        self.as_user(self.student)
        content = self.client.get(f'/api/blocks/{self.code.id}/').data['content']

        self.assertEqual(content['tests'], [{'input': 'in1', 'expected': 'out1'},
                                            {'input': 'in2', 'expected': 'out2'}])
        self.assertEqual(content['hidden_test_count'], 1)

    def test_explicit_visible_flags(self):
        self.code.content['tests'] = [
            {'input': 'in1', 'expected': 'out1', 'visible': False},
            {'input': 'in2', 'expected': 'out2', 'visible': True},
            {'input': self.HIDDEN_IN, 'expected': self.HIDDEN_OUT},  # no flag → hidden
        ]
        self.code.save()
        self.as_user(self.student)

        content = self.client.get(f'/api/blocks/{self.code.id}/').data['content']

        self.assertEqual([t['input'] for t in content['tests']], ['in2'])
        self.assertEqual(content['hidden_test_count'], 2)

    def test_visible_flag_is_validated(self):
        self.as_user(self.author)
        base = {'lesson': str(self.lesson.id), 'type': 'CODE', 'order_index': 9}
        ok = dict(base, content={'prompt': 'p', 'starter_code': '',
                                 'tests': [{'input': '', 'expected': '1', 'visible': True}]})
        bad = dict(base, order_index=10, content={'prompt': 'p', 'starter_code': '',
                                                  'tests': [{'input': '', 'expected': '1', 'visible': 'yes'}]})

        self.assertEqual(self.client.post('/api/blocks/', ok, format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/blocks/', bad, format='json').status_code, 400)

    def test_hidden_code_is_validated(self):
        self.as_user(self.author)
        content = {'prompt': 'p', 'starter_code': ''}
        for i, (extra, status_code) in enumerate([
                ({}, 201),                                     # optional
                ({'header': 'import math', 'footer': ''}, 201),
                ({'header': None}, 400),
                ({'footer': ['print(1)']}, 400)]):
            with self.subTest(extra=extra):
                response = self.client.post('/api/blocks/', {
                    'lesson': str(self.lesson.id), 'type': 'CODE', 'order_index': 20 + i,
                    'content': dict(content, **extra)}, format='json')
                self.assertEqual(response.status_code, status_code, response.data)

    # --- CODE: run-tests grades with the stored tests ----------------------

    def run_tests(self, code='print(1)', **extra):
        return self.client.post(RUN_TESTS_URL, {'block_id': str(self.code.id), 'code': code,
                                                'version': 'Python 3.12', **extra}, format='json')

    def test_run_tests_ignores_browser_tests_and_records_success(self):
        self.as_user(self.student)
        outputs = {'in1': 'out1', 'in2': 'out2', self.HIDDEN_IN: self.HIDDEN_OUT}
        with fake_program(outputs) as run:
            response = self.run_tests(tests=[{'input': 'evil', 'expected': 'anything'}],
                                      is_correct=False)

        self.assertEqual([c.kwargs['stdin'] for c in run.call_args_list],
                         ['in1', 'in2', self.HIDDEN_IN])
        self.assertEqual(response.data['status'], 'success')
        self.assertTrue(response.data['is_correct'])
        self.assertTrue(response.data['recorded'])
        self.assertEqual(response.data['total'], 3)
        # Hidden test: passed / not passed only.
        self.assertEqual(response.data['results'][2], {'test_number': 3, 'passed': True, 'hidden': True})
        for marker in [self.HIDDEN_IN, self.HIDDEN_OUT]:
            self.assertNotIn(marker, response.content.decode())

        progress = Progress.objects.get(student=self.student, block=self.code)
        self.assertTrue(progress.is_correct)
        self.assertEqual(progress.answer, {'code': 'print(1)'})
        self.assertEqual(Attempt.objects.filter(student=self.student, block=self.code).count(), 1)

    def test_run_tests_runs_the_blocks_hidden_code(self):
        self.as_user(self.student)
        with fake_program({'in1': 'out1', 'in2': 'out2', self.HIDDEN_IN: self.HIDDEN_OUT}) as run:
            response = self.run_tests(header='print("evil")', footer='print("evil")')

        self.assertEqual(response.data['status'], 'success')
        # Every test: the block's stored header / footer, never the request's.
        self.assertEqual([(c.args, c.kwargs) for c in run.call_args_list], [
            (('print(1)',), {'stdin': stdin, 'version': 'Python 3.12',
                             'header': self.HEADER, 'footer': self.FOOTER})
            for stdin in ['in1', 'in2', self.HIDDEN_IN]])
        # Progress / Attempt keep the student's code only.
        self.assertEqual(Progress.objects.get(student=self.student, block=self.code).answer,
                         {'code': 'print(1)'})
        self.assertEqual(Attempt.objects.get(student=self.student, block=self.code).answer,
                         {'code': 'print(1)'})

    def test_run_code_uses_stored_hidden_code_and_ignores_the_request(self):
        for user in [self.student, self.author]:
            with self.subTest(user=user.username):
                self.as_user(user)
                with fake_run(stdout='ok\n') as run:
                    response = self.client.post(RUN_CODE_URL, {
                        'block_id': str(self.code.id), 'code': 'print(1)', 'stdin': '5',
                        'version': 'Python 3.12', 'header': 'print("evil")', 'footer': ''},
                        format='json')

                self.assertEqual(response.status_code, 200)
                run.assert_called_once_with('print(1)', stdin='5', version='Python 3.12',
                                            header=self.HEADER, footer=self.FOOTER)
                for marker in [self.HEADER, self.FOOTER]:
                    self.assertNotIn(marker, response.content.decode())

    def test_block_without_hidden_code_runs_as_before(self):
        self.code.content.pop('header')
        self.code.content.pop('footer')
        self.code.save()
        self.as_user(self.student)
        with fake_program({'in1': 'out1', 'in2': 'out2', self.HIDDEN_IN: self.HIDDEN_OUT}) as run:
            self.run_tests()
        with fake_run() as run_code:
            self.client.post(RUN_CODE_URL, {'block_id': str(self.code.id), 'code': 'print(1)',
                                            'stdin': '', 'version': 'Python 3.12'}, format='json')

        for call in run.call_args_list + run_code.call_args_list:
            self.assertEqual((call.kwargs['header'], call.kwargs['footer']), ('', ''))

    def test_failing_hidden_test_reveals_nothing(self):
        self.as_user(self.student)
        with fake_program({'in1': 'out1', 'in2': 'out2', self.HIDDEN_IN: 'MARK-ACTUAL'}):
            response = self.run_tests()

        self.assertEqual(response.data['status'], 'wrong_answer')
        self.assertEqual((response.data['test_number'], response.data['hidden']), (3, True))
        for key in ['input', 'expected', 'actual', 'stderr']:
            self.assertNotIn(key, response.data)
        for marker in [self.HIDDEN_IN, self.HIDDEN_OUT, 'MARK-ACTUAL']:
            self.assertNotIn(marker, response.content.decode())
        self.assertFalse(response.data['is_correct'])
        self.assertFalse(Progress.objects.get(student=self.student, block=self.code).is_correct)
        self.assertFalse(Attempt.objects.get(student=self.student, block=self.code).is_correct)

    def test_error_on_hidden_test_hides_stderr(self):
        self.as_user(self.student)
        with fake_program({'in1': 'out1', 'in2': 'out2'}, errors={self.HIDDEN_IN: 'MARK-STDERR'}):
            response = self.run_tests()

        self.assertEqual((response.data['status'], response.data['hidden']), ('error', True))
        self.assertNotIn('MARK-STDERR', response.content.decode())

    def test_failing_visible_test_shows_details(self):
        self.as_user(self.student)
        with fake_program({'in1': 'wrong'}):
            response = self.run_tests()

        self.assertEqual(response.data['status'], 'wrong_answer')
        self.assertEqual(
            (response.data['test_number'], response.data['hidden'], response.data['input'],
             response.data['expected'], response.data['actual']),
            (1, False, 'in1', 'out1', 'wrong'))

    def test_solved_code_block_stays_solved(self):
        self.as_user(self.student)
        with fake_program({'in1': 'out1', 'in2': 'out2', self.HIDDEN_IN: self.HIDDEN_OUT}):
            self.run_tests()
        with fake_program({}):
            again = self.run_tests(code='print("broken")')

        self.assertFalse(again.data['is_correct'])
        self.assertFalse(again.data['recorded'])
        progress = Progress.objects.get(student=self.student, block=self.code)
        self.assertTrue(progress.is_correct)
        self.assertEqual(progress.answer, {'code': 'print(1)'})
        self.assertEqual(Attempt.objects.filter(block=self.code).count(), 1)

    def test_code_via_progress_submit_is_rejected(self):
        self.as_user(self.student)
        response = self.client.post('/api/progress/submit/', {
            'block': str(self.code.id), 'answer': {'code': 'x'}, 'is_correct': True}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Progress.objects.filter(block=self.code).exists())

    # --- QUIZ / FILL: server grading and explanations ----------------------

    def submit(self, block, answer, **extra):
        return self.client.post('/api/progress/submit/',
                                {'block': str(block.id), 'answer': answer, **extra}, format='json')

    def test_client_is_correct_is_ignored(self):
        self.as_user(self.student)
        response = self.submit(self.quiz, {'selected': 0}, is_correct=True)

        self.assertFalse(response.data['is_correct'])
        self.assertFalse(Progress.objects.get(student=self.student, block=self.quiz).is_correct)

    def test_quiz_explanation_only_after_correct_answer(self):
        self.as_user(self.student)
        wrong = self.submit(self.quiz, {'selected': 0})
        right = self.submit(self.quiz, {'selected': 2})

        self.assertEqual((wrong.data['is_correct'], wrong.data['feedback']), (False, {}))
        self.assertNotIn(self.QUIZ_EXPL, wrong.content.decode())
        self.assertTrue(right.data['is_correct'])
        self.assertEqual(right.data['feedback'], {'explanation': self.QUIZ_EXPL})
        self.assertEqual(Attempt.objects.filter(block=self.quiz).count(), 2)

    def test_fill_gap_results_and_explanation_only_when_correct(self):
        self.as_user(self.student)
        partial = self.submit(self.fill, {'blanks': [self.FILL_ALT.upper(), 'nope']})
        right = self.submit(self.fill, {'blanks': [self.FILL_ANSWER, 'x']})

        self.assertFalse(partial.data['is_correct'])
        self.assertEqual(partial.data['feedback'], {'blanks_correct': [True, False]})
        self.assertTrue(right.data['is_correct'])
        self.assertEqual(right.data['feedback'],
                         {'blanks_correct': [True, True], 'explanation': self.FILL_EXPL})

    def test_resolving_a_solved_block_is_graded_but_not_recorded(self):
        self.as_user(self.student)
        self.submit(self.quiz, {'selected': 2})
        practice = self.submit(self.quiz, {'selected': 1})

        self.assertEqual(practice.status_code, 200)
        self.assertFalse(practice.data['is_correct'])
        self.assertFalse(practice.data['recorded'])
        progress = Progress.objects.get(student=self.student, block=self.quiz)
        self.assertTrue(progress.is_correct)
        self.assertEqual(progress.answer, {'selected': 2})
        self.assertEqual(Attempt.objects.filter(block=self.quiz).count(), 1)

    def test_restore_on_page_load_uses_own_saved_answers(self):
        self.as_user(self.student)
        self.submit(self.quiz, {'selected': 2})                      # solved
        self.submit(self.fill, {'blanks': [self.FILL_ANSWER, 'no']})  # not solved

        restored = {p['block_type']: p for p in
                    self.client.get(f'/api/progress/course/{self.course.id}/').data}

        self.assertTrue(restored['QUIZ']['is_correct'])
        self.assertEqual(restored['QUIZ']['answer'], {'selected': 2})
        self.assertEqual(restored['QUIZ']['feedback'], {'explanation': self.QUIZ_EXPL})
        self.assertFalse(restored['FILL']['is_correct'])
        self.assertEqual(restored['FILL']['feedback'], {'blanks_correct': [True, False]})


class CodeRunnerAccessTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.other_author = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.enrolled = User.objects.create_user(username='enrolled', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        lesson = Lesson.objects.create(course=course, title='Lesson', order_index=1)
        cls.code_block = Block.objects.create(lesson=lesson, type='CODE', order_index=1, content={
            'prompt': 'p', 'starter_code': '', 'tests': [{'input': '1', 'expected': '2'}]})
        cls.text_block = Block.objects.create(
            lesson=lesson, type='TEXT', order_index=2, content={'html': '<p>x</p>'})
        Enrollment.objects.create(student=cls.enrolled, course=course)

    def setUp(self):
        cache.clear()  # throttle counters live in the default cache

    def run_code(self, user, block_id, url=RUN_CODE_URL):
        if user:
            self.client.force_authenticate(user)
        body = {'code': 'print(2)', 'stdin': '1', 'version': 'Python 3.12',
                'tests': [{'input': '1', 'expected': '2'}]}
        if block_id is not None:
            body['block_id'] = str(block_id)
        return self.client.post(url, body, format='json')

    def test_anonymous_gets_401(self):
        with fake_run() as run:
            for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                self.assertEqual(self.run_code(None, self.code_block.id, url).status_code, 401, url)
        run.assert_not_called()

    def test_not_enrolled_student_gets_403(self):
        with fake_run() as run:
            for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                self.assertEqual(self.run_code(self.outsider, self.code_block.id, url).status_code, 403, url)
        run.assert_not_called()

    def test_other_author_gets_403(self):
        with fake_run() as run:
            response = self.run_code(self.other_author, self.code_block.id)
        self.assertEqual(response.status_code, 403)
        run.assert_not_called()

    def test_enrolled_student_can_run_code_and_tests(self):
        with fake_run() as run:
            code = self.run_code(self.enrolled, self.code_block.id, RUN_CODE_URL)
            tests = self.run_code(self.enrolled, self.code_block.id, RUN_TESTS_URL)

        self.assertEqual(code.status_code, 200)
        self.assertEqual(code.data['stdout'], '2\n')
        self.assertEqual(tests.status_code, 200)
        self.assertEqual(tests.data['status'], 'success')
        self.assertEqual(run.call_count, 2)

    def test_course_author_can_run_code(self):
        with fake_run() as run:
            response = self.run_code(self.author, self.code_block.id)
        self.assertEqual(response.status_code, 200)
        run.assert_called_once()

    def test_unknown_or_malformed_block_gets_404(self):
        with fake_run() as run:
            for block_id in ['3fa85f64-5717-4562-b3fc-2c963f66afa6', 'not-a-uuid']:
                for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                    response = self.run_code(self.enrolled, block_id, url)
                    self.assertEqual(response.status_code, 404, (block_id, url))
        run.assert_not_called()

    def test_missing_block_id_gets_400(self):
        with fake_run() as run:
            response = self.run_code(self.enrolled, None)
        self.assertEqual(response.status_code, 400)
        run.assert_not_called()

    def test_non_code_block_gets_400(self):
        with fake_run() as run:
            for url in [RUN_CODE_URL, RUN_TESTS_URL]:
                self.assertEqual(self.run_code(self.enrolled, self.text_block.id, url).status_code, 400, url)
        run.assert_not_called()

    def test_throttle_returns_429_when_exceeded(self):
        # The rate is read per request from this dict, so patching it overrides settings.
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'code_run': '3/min'}), fake_run():
            statuses = [self.run_code(self.enrolled, self.code_block.id, url).status_code
                        for url in [RUN_CODE_URL, RUN_TESTS_URL, RUN_CODE_URL, RUN_TESTS_URL]]
        # One shared budget for both endpoints: the 4th call in a minute is refused.
        self.assertEqual(statuses, [200, 200, 200, 429])

    def test_throttle_is_per_user(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'code_run': '1/min'}), fake_run():
            first = self.run_code(self.enrolled, self.code_block.id).status_code
            second = self.run_code(self.enrolled, self.code_block.id).status_code
            author = self.run_code(self.author, self.code_block.id).status_code
        self.assertEqual((first, second, author), (200, 429, 200))


class RegistrationRoleTests(APITestCase):
    def register(self, username, **extra):
        return self.client.post(
            REGISTER_URL, {'username': username, 'password': 'Sup3r-secret-pass', **extra},
            format='json')

    def test_client_supplied_role_is_ignored(self):
        for username, role in [('wants_author', 'AUTHOR'), ('wants_admin', 'ADMIN'),
                               ('bogus_role', 'SUPERUSER')]:
            response = self.register(username, role=role)

            self.assertEqual(response.status_code, 201, role)
            self.assertEqual(response.data['user']['role'], 'STUDENT', role)
            user = User.objects.get(username=username)
            self.assertEqual(user.role, 'STUDENT', role)
            self.assertFalse(user.is_staff or user.is_superuser, role)

    def test_no_role_registers_student(self):
        response = self.register('plain')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user']['role'], 'STUDENT')
        self.assertEqual(User.objects.get(username='plain').role, 'STUDENT')


class RegistrationFlowTests(APITestCase):
    """Sign-up logs the user in (same token pair as login) or explains the error."""

    def register(self, username='newbie', password='Sup3r-secret-pass', **extra):
        return self.client.post(
            REGISTER_URL, {'username': username, 'password': password, **extra}, format='json')

    def test_success_returns_user_and_working_token_pair(self):
        response = self.register()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user']['username'], 'newbie')
        tokens = response.data['tokens']
        self.assertEqual(set(tokens), {'access', 'refresh'})

        # The access token logs the new user in...
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        me = self.client.get('/api/auth/me/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['username'], 'newbie')
        # ...and the refresh token renews it, exactly as after /login/.
        self.client.credentials()
        refreshed = self.client.post('/api/auth/token/refresh/', {'refresh': tokens['refresh']},
                                     format='json')
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn('access', refreshed.data)

    def test_stale_token_in_header_does_not_block_sign_up(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer stale.garbage.token')

        self.assertEqual(self.register().status_code, 201)

    def assert_rejected(self, response, code):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], code)
        self.assertNotIn('tokens', response.data)

    def test_empty_fields(self):
        response = self.register(username='  ', password='')

        self.assert_rejected(response, 'required')
        self.assertEqual(response.data['fields'], ['username', 'password'])
        self.assertFalse(User.objects.exists())

    def test_username_taken(self):
        User.objects.create_user(username='newbie', password='x')

        self.assert_rejected(self.register(), 'username_taken')
        self.assertEqual(User.objects.count(), 1)

    def test_username_taken_ignores_case(self):
        User.objects.create_user(username='alice', password='Sup3r-secret-pass')

        for username in ['Alice', 'ALICE', 'aLiCe']:
            self.assert_rejected(self.register(username=username), 'username_taken')
        self.assertEqual(User.objects.count(), 1)
        # Login itself stays exact: only the stored spelling works.
        login = lambda name: self.client.post(
            '/api/auth/login/', {'username': name, 'password': 'Sup3r-secret-pass'}, format='json')
        self.assertEqual(login('alice').status_code, 200)
        self.assertEqual(login('Alice').status_code, 401)

    def test_invalid_username(self):
        self.assert_rejected(self.register(username='two words'), 'invalid_username')
        self.assertFalse(User.objects.exists())

    def test_weak_passwords_use_the_project_validators(self):
        for password, expected in [('1', 'password_too_short'),
                                   ('48261937', 'password_entirely_numeric'),
                                   ('password', 'password_too_common'),
                                   ('newbie123', 'password_too_similar')]:
            response = self.register(password=password)

            self.assert_rejected(response, 'weak_password')
            self.assertIn(expected, response.data['codes'], password)
            self.assertTrue(response.data['messages'], password)
        self.assertFalse(User.objects.exists())

    def test_weak_password_reports_the_configured_minimum_length(self):
        self.assertEqual(self.register(password='1').data['min_length'], 8)  # Django's default

        validators = [{'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
                       'OPTIONS': {'min_length': 12}}]
        with self.settings(AUTH_PASSWORD_VALIDATORS=validators):
            response = self.register(password='Short-pass1')  # 11 characters
        self.assert_rejected(response, 'weak_password')
        self.assertEqual(response.data['codes'], ['password_too_short'])
        self.assertEqual(response.data['min_length'], 12)


class StudentCannotChangeOwnRoleTests(APITestCase):
    """There is no self-update endpoint; these pin that down and guard the serializer."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')

    def test_me_endpoint_is_read_only(self):
        self.client.force_authenticate(self.student)

        for method in ['put', 'patch', 'post']:
            response = getattr(self.client, method)(
                '/api/auth/me/', {'role': 'AUTHOR'}, format='json')
            self.assertEqual(response.status_code, 405, method)

        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'STUDENT')

    def test_registering_again_while_logged_in_does_not_change_role(self):
        self.client.force_authenticate(self.student)

        self.client.post(REGISTER_URL, {'username': 'student', 'password': 'y', 'role': 'AUTHOR'},
                         format='json')

        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'STUDENT')

    def test_user_serializer_role_is_read_only(self):
        serializer = UserSerializer(self.student, data={'role': 'ADMIN'}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'STUDENT')

ENROL_URL = '/api/enrollments/'


class SelfEnrolmentTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.admin = User.objects.create_user(username='admin', password='x', role='ADMIN')
        cls.free = Course.objects.create(
            title='Free course', author=cls.author, is_published=True, price=0)
        cls.paid = Course.objects.create(
            title='Paid course', author=cls.author, is_published=True, price=Decimal('1990'))
        cls.draft = Course.objects.create(
            title='Draft course', author=cls.author, is_published=False, price=0)

    def enrol(self, user, course_id):
        if user:
            self.client.force_authenticate(user)
        return self.client.post(ENROL_URL, {'course': str(course_id)}, format='json')

    def test_anonymous_gets_401(self):
        response = self.enrol(None, self.free.id)

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Enrollment.objects.exists())

    def test_author_gets_403(self):
        response = self.enrol(self.author, self.free.id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], 'Записаться на курс может только учащийся.')
        self.assertEqual(response.data['course_slug'], self.free.slug)
        self.assertFalse(Enrollment.objects.exists())

    def test_admin_role_gets_403(self):
        response = self.enrol(self.admin, self.free.id)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Enrollment.objects.exists())

    def test_unpublished_course_gets_404(self):
        response = self.enrol(self.student, self.draft.id)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['detail'], 'Курс не найден.')
        self.assertIsNone(response.data['course_slug'])
        self.assertFalse(Enrollment.objects.exists())

    def test_missing_or_malformed_course_gets_404(self):
        for course_id in ['3fa85f64-5717-4562-b3fc-2c963f66afa6', 'not-a-uuid', '']:
            response = self.enrol(self.student, course_id)
            self.assertEqual(response.status_code, 404, course_id)
        response = self.client.post(ENROL_URL, {}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Enrollment.objects.exists())

    def test_paid_course_gets_403(self):
        response = self.enrol(self.student, self.paid.id)

        self.assertEqual(response.status_code, 403)
        self.assertIn('платный', response.data['detail'])
        self.assertEqual(response.data['course_slug'], self.paid.slug)
        self.assertFalse(Enrollment.objects.exists())

    def test_role_is_checked_before_course(self):
        # An author asking for a missing course still gets the role error.
        response = self.enrol(self.author, '3fa85f64-5717-4562-b3fc-2c963f66afa6')

        self.assertEqual(response.status_code, 403)

    def test_free_published_course_creates_exactly_one_enrollment(self):
        response = self.enrol(self.student, self.free.id)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['course'], self.free.id)
        self.assertEqual(response.data['student'], self.student.id)
        self.assertEqual(
            Enrollment.objects.filter(student=self.student, course=self.free).count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_repeat_call_is_idempotent(self):
        first = self.enrol(self.student, self.free.id)
        second = self.enrol(self.student, self.free.id)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data['id'], first.data['id'])
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_list_still_returns_own_enrollments(self):
        Enrollment.objects.create(student=self.student, course=self.free)
        other = User.objects.create_user(username='other', password='x', role='STUDENT')
        Enrollment.objects.create(student=other, course=self.free)
        self.client.force_authenticate(self.student)

        response = self.client.get(ENROL_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([e['student'] for e in response.data], [self.student.id])


class RemovedEnrolmentRoutesTests(APITestCase):
    """The old EnrollmentViewSet routes are gone, so nothing bypasses the rules above."""

    @classmethod
    def setUpTestData(cls):
        author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.free = Course.objects.create(
            title='Free course', author=author, is_published=True, price=0)
        cls.paid = Course.objects.create(
            title='Paid course', author=author, is_published=True, price=Decimal('1990'))

    def test_old_enroll_action_and_format_suffix_routes_are_gone(self):
        self.client.force_authenticate(self.student)
        enrollment = Enrollment.objects.create(student=self.student, course=self.free)

        attempts = [
            self.client.post('/api/enrollments/enroll/', {'course': str(self.paid.id)}, format='json'),
            self.client.post('/api/enrollments.json', {'course': str(self.paid.id)}, format='json'),
            self.client.patch(f'/api/enrollments/{enrollment.id}.json',
                              {'course': str(self.paid.id)}, format='json'),
        ]

        for response in attempts:
            self.assertEqual(response.status_code, 404, response.request['PATH_INFO'])
        self.assertFalse(Enrollment.objects.filter(course=self.paid).exists())


class TeacherEnrollStudentTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='alice', password='x', role='STUDENT')
        # Teachers may enrol anyone, including into paid and unpublished courses.
        cls.paid_draft = Course.objects.create(
            title='Paid draft', author=cls.author, is_published=False, price=Decimal('1990'))

    def test_teacher_can_enrol_a_student(self):
        self.client.force_authenticate(self.author)

        response = self.client.post(
            f'/api/courses/{self.paid_draft.id}/enroll_student/', {'username': 'alice'}, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            Enrollment.objects.filter(student=self.student, course=self.paid_draft).exists())

    def test_student_cannot_use_teacher_action(self):
        self.client.force_authenticate(self.student)

        response = self.client.post(
            f'/api/courses/{self.paid_draft.id}/enroll_student/', {'username': 'alice'}, format='json')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Enrollment.objects.exists())


class StudentProgressQuizCountTests(APITestCase):
    """"Тестов верно" on the progress page counts quizzes on both sides.

    Reproduces the reported case: a student with correct quizzes and also
    solved CODE and FILL tasks saw more correct answers than quizzes
    ("14/13"), because solved non-quiz tasks were counted as correct quizzes.
    """

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='alice', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='String methods', author=cls.author, is_published=True)
        lesson = Lesson.objects.create(course=cls.course, title='Lesson', order_index=1)
        Enrollment.objects.create(student=cls.student, course=cls.course)

        blocks = {}
        for order, (name, type_) in enumerate([
                ('text', 'TEXT'), ('quiz1', 'QUIZ'), ('quiz2', 'QUIZ'), ('quiz3', 'QUIZ'),
                ('code1', 'CODE'), ('code2', 'CODE'), ('fill', 'FILL')], start=1):
            blocks[name] = Block.objects.create(lesson=lesson, type=type_, order_index=order, content={})

        # 2 of 3 quizzes correct, 1 wrong; both code tasks and the fill task solved.
        for name, correct in [('quiz1', True), ('quiz2', True), ('quiz3', False),
                              ('code1', True), ('code2', True), ('fill', True)]:
            Progress.objects.create(student=cls.student, block=blocks[name], lesson=lesson,
                                    completed=True, is_correct=correct)

    def progress(self, viewer):
        self.client.force_authenticate(viewer)
        response = self.client.get(
            f'/api/progress/student/{self.student.id}/course/{self.course.id}/')
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_correct_answers_count_only_quizzes(self):
        for viewer in [self.author, self.student]:  # the teacher's view and the student's own
            data = self.progress(viewer)

            self.assertEqual(data['total_quizzes'], 3)
            self.assertEqual(data['correct_answers'], 2)  # not 5 (2 quizzes + 2 code + 1 fill)
            self.assertLessEqual(data['correct_answers'], data['total_quizzes'])
            # Solved CODE/FILL tasks still count where they belong.
            self.assertEqual(data['completed_blocks'], 6)

    def test_matches_the_stats_view(self):
        self.client.force_authenticate(self.student)
        stats = self.client.get('/api/progress/stats/').data
        course_stats = next(s for s in stats if str(s['course_id']) == str(self.course.id))

        data = self.progress(self.student)
        self.assertEqual((data['correct_answers'], data['total_quizzes']),
                         (course_stats['correct_answers'], course_stats['total_quizzes']))


class ChatMessageEndpointTests(APITestCase):
    """
    POST /api/messages/ follows the same rule as the chat WebSocket
    (api/chat.py): only the course author ↔ an enrolled student, and messages
    up to MAX_MESSAGE_LENGTH characters.
    """

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.classmate = User.objects.create_user(username='classmate', password='x', role='STUDENT')
        cls.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        Enrollment.objects.create(student=cls.student, course=cls.course)
        Enrollment.objects.create(student=cls.classmate, course=cls.course)

    def post(self, sender, receiver, text='Привет', course=None):
        self.client.force_authenticate(sender)
        return self.client.post('/api/messages/', {
            'course': str(course or self.course.id),
            'receiver': receiver.id if hasattr(receiver, 'id') else receiver,
            'text': text,
        }, format='json')

    def test_student_and_author_can_write_to_each_other(self):
        for sender, receiver in [(self.student, self.author), (self.author, self.student)]:
            response = self.post(sender, receiver)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['sender'], sender.id)
            self.assertEqual(response.data['receiver'], receiver.id)
        self.assertEqual(Message.objects.count(), 2)

    def test_outsider_is_refused(self):
        response = self.post(self.outsider, self.author)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_cannot_write_to_an_outsider(self):
        self.assertEqual(self.post(self.author, self.outsider).status_code, 403)
        self.assertEqual(self.post(self.student, self.outsider).status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_students_cannot_write_to_each_other_or_themselves(self):
        self.assertEqual(self.post(self.student, self.classmate).status_code, 403)
        self.assertEqual(self.post(self.author, self.author).status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_unknown_or_malformed_course_is_refused(self):
        other = Course.objects.create(title='Other', author=self.author)
        self.assertEqual(self.post(self.student, self.author, course=other.id).status_code, 403)
        self.assertEqual(self.post(self.student, self.author, course='not-a-uuid').status_code, 403)
        self.assertEqual(self.post(self.student, 'abc').status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_length_limit(self):
        self.assertEqual(self.post(self.student, self.author, 'я' * MAX_MESSAGE_LENGTH).status_code, 201)
        response = self.post(self.student, self.author, 'я' * (MAX_MESSAGE_LENGTH + 1))
        self.assertEqual(response.status_code, 400)
        self.assertIn(str(MAX_MESSAGE_LENGTH), str(response.data['detail']))
        self.assertEqual(Message.objects.count(), 1)

    def test_blank_text_is_rejected(self):
        self.assertEqual(self.post(self.student, self.author, '   ').status_code, 400)

    def test_anonymous_is_refused(self):
        response = self.client.post('/api/messages/', {
            'course': str(self.course.id), 'receiver': self.author.id, 'text': 'x'}, format='json')
        self.assertEqual(response.status_code, 401)


class ChatConsumerTests(TransactionTestCase):
    """
    The chat WebSocket: close codes the client relies on (4001 log in again,
    4003 never allowed, including a malformed course id) and the length limit.
    TransactionTestCase: the consumer reads the database from another thread.
    """

    def setUp(self):
        self.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        self.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        self.outsider = User.objects.create_user(username='outsider', password='x', role='STUDENT')
        self.course = Course.objects.create(title='Course', author=self.author, is_published=True)
        Enrollment.objects.create(student=self.student, course=self.course)

    def connect(self, user, course_id, other_id):
        from backend.asgi import application
        from rest_framework_simplejwt.tokens import AccessToken
        token = str(AccessToken.for_user(user)) if user else 'bad'
        return WebsocketCommunicator(application, f'/ws/chat/{course_id}/{other_id}/?token={token}')

    async def assert_closed_with(self, communicator, code):
        # Accepted, then closed with the code: a browser only sees the code
        # that way (a rejected handshake reaches it as 1006).
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        self.assertEqual(await communicator.receive_output(), {'type': 'websocket.close', 'code': code})

    def test_close_codes(self):
        async def run():
            await self.assert_closed_with(self.connect(None, self.course.id, self.author.id), 4001)
            await self.assert_closed_with(self.connect(self.outsider, self.course.id, self.author.id), 4003)
            # Matches the URL pattern ([0-9a-f-]+) but is not a UUID: refused, not a server error.
            await self.assert_closed_with(self.connect(self.student, 'abc-123', self.author.id), 4003)
        async_to_sync(run)()

    def test_message_is_saved_and_delivered_to_both_sides(self):
        async def run():
            student = self.connect(self.student, self.course.id, self.author.id)
            author = self.connect(self.author, self.course.id, self.student.id)
            self.assertTrue((await student.connect())[0])
            self.assertTrue((await author.connect())[0])
            await student.send_json_to({'text': '  Здравствуйте!  '})
            for side in (student, author):
                frame = await side.receive_json_from()
                self.assertEqual(frame['text'], 'Здравствуйте!')
                self.assertEqual(frame['sender'], self.student.id)
            await student.disconnect()
            await author.disconnect()
        async_to_sync(run)()
        self.assertEqual(Message.objects.count(), 1)

    def test_too_long_message_is_rejected_to_the_sender_only(self):
        async def run():
            student = self.connect(self.student, self.course.id, self.author.id)
            author = self.connect(self.author, self.course.id, self.student.id)
            await student.connect()
            await author.connect()
            await student.send_json_to({'text': 'я' * (MAX_MESSAGE_LENGTH + 1)})
            self.assertEqual(await student.receive_json_from(),
                             {'error': 'too_long', 'max_length': MAX_MESSAGE_LENGTH})
            self.assertTrue(await author.receive_nothing())
            await student.disconnect()
            await author.disconnect()
        async_to_sync(run)()
        self.assertEqual(Message.objects.count(), 0)
