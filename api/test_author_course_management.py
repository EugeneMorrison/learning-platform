from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User


class AuthorCourseActivityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', password='x', role='AUTHOR')
        cls.other = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.old = Course.objects.create(title='Old', author=cls.author, sort_order=0)
        cls.recent = Course.objects.create(title='Recent', author=cls.author, sort_order=99)
        cls.foreign = Course.objects.create(title='Foreign', author=cls.other)
        cls.lesson = Lesson.objects.create(course=cls.old, title='Lesson', order_index=1)
        cls.block = Block.objects.create(lesson=cls.lesson, type='TEXT', order_index=1, content={'html': 'Text'})
        cls.past = timezone.now() - timedelta(days=10)
        Course.objects.filter(pk=cls.old.pk).update(created_at=cls.past, updated_at=cls.past)
        Course.objects.filter(pk=cls.recent.pk).update(updated_at=timezone.now() - timedelta(days=2))
        Lesson.objects.filter(pk=cls.lesson.pk).update(updated_at=cls.past)
        Block.objects.filter(pk=cls.block.pk).update(updated_at=cls.past)

    def setUp(self):
        self.client.force_authenticate(self.author)

    def course_ids(self):
        response = self.client.get('/api/courses/my_courses/')
        self.assertEqual(response.status_code, 200)
        return [str(row['id']) for row in response.data]

    def test_recent_changes_override_manual_catalog_order_and_exclude_other_authors(self):
        self.assertEqual(self.course_ids(), [str(self.recent.pk), str(self.old.pk)])
        # Public/manual catalog ordering is not changed by the dashboard sort.
        self.assertLess(list(Course.objects.values_list('pk', flat=True)).index(self.old.pk),
                        list(Course.objects.values_list('pk', flat=True)).index(self.recent.pk))

    def test_editing_course_moves_it_first(self):
        response = self.client.patch(f'/api/courses/{self.old.pk}/', {'title': 'Changed'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.course_ids()[0], str(self.old.pk))

    def test_lesson_changes_are_activity_without_course_timestamp_changes(self):
        self.lesson.title = 'Changed lesson'
        self.lesson.save()
        self.assertEqual(self.course_ids()[0], str(self.old.pk))
        self.old.refresh_from_db()
        self.assertEqual(self.old.updated_at, self.past)

    def test_step_changes_before_history_was_enabled_are_activity(self):
        self.block.content = {'html': 'New theory'}
        self.block.save()
        self.assertEqual(self.course_ids()[0], str(self.old.pk))

    def test_deleted_step_still_counts_as_recent_activity(self):
        response = self.client.delete(f'/api/blocks/{self.block.pk}/')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.course_ids()[0], str(self.old.pk))

    def test_reordering_uses_history_even_when_bulk_updates_do_not_touch_timestamps(self):
        second = Block.objects.create(lesson=self.lesson, type='TEXT', order_index=2, content={})
        Block.objects.filter(pk=second.pk).update(updated_at=self.past)
        response = self.client.post(f'/api/blocks/{self.block.pk}/reorder/', {'new_order': 2}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.course_ids()[0], str(self.old.pk))

    def test_empty_courses_with_equal_activity_have_stable_order(self):
        Course.objects.filter(author=self.author).update(updated_at=self.past, created_at=self.past)
        expected = sorted([str(self.old.pk), str(self.recent.pk)])
        self.assertEqual(self.course_ids(), expected)
        self.assertEqual(self.course_ids(), expected)


class AuthorRemoveStudentTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='teacher', password='x', role='AUTHOR')
        cls.other = User.objects.create_user(username='other', password='x', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', password='x', role='STUDENT')
        cls.classmate = User.objects.create_user(username='classmate', password='x', role='STUDENT')
        cls.course = Course.objects.create(title='Course', author=cls.author, is_published=True)
        cls.other_course = Course.objects.create(title='Other course', author=cls.author)
        cls.enrollment = Enrollment.objects.create(student=cls.student, course=cls.course)
        cls.other_enrollment = Enrollment.objects.create(student=cls.student, course=cls.other_course)
        cls.classmate_enrollment = Enrollment.objects.create(student=cls.classmate, course=cls.course)
        cls.lesson = Lesson.objects.create(course=cls.course, title='Lesson', order_index=1)
        cls.block = Block.objects.create(lesson=cls.lesson, type='QUIZ', order_index=1, content={})
        cls.progress = Progress.objects.create(student=cls.student, lesson=cls.lesson, block=cls.block,
                                              answer={'selected': 0}, is_correct=True)
        cls.attempt = Attempt.objects.create(student=cls.student, block=cls.block, answer={'selected': 0}, is_correct=True)

    def remove(self, user, course=None, enrollment=None):
        self.client.force_authenticate(user)
        return self.client.delete(f'/api/courses/{(course or self.course).pk}/enrollments/{(enrollment or self.enrollment).pk}/')

    def test_owner_revokes_all_lesson_access_but_preserves_work_and_other_enrollments(self):
        self.assertEqual(self.remove(self.author).status_code, 204)
        self.assertFalse(Enrollment.objects.filter(pk=self.enrollment.pk).exists())
        self.assertTrue(Enrollment.objects.filter(pk=self.other_enrollment.pk).exists())
        self.assertTrue(Enrollment.objects.filter(pk=self.classmate_enrollment.pk).exists())
        self.assertTrue(Progress.objects.filter(pk=self.progress.pk).exists())
        self.assertTrue(Attempt.objects.filter(pk=self.attempt.pk).exists())
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(f'/api/lessons/{self.lesson.pk}/').status_code, 404)
        self.assertEqual(self.client.get('/api/lessons/outline/', {'course': str(self.course.pk)}).status_code, 404)
        self.assertEqual(self.client.post('/api/progress/submit/', {'block': str(self.block.pk), 'answer': {'selected': 0}}, format='json').status_code, 403)
        self.client.force_authenticate(self.author)
        rows = self.client.get('/api/courses/my_courses/').data
        row = next(row for row in rows if str(row['id']) == str(self.course.pk))
        self.assertEqual((row['student_count'], row['students_solved']), (1, 0))

    def test_other_author_cannot_remove_students(self):
        self.assertEqual(self.remove(self.other).status_code, 403)
        self.assertTrue(Enrollment.objects.filter(pk=self.enrollment.pk).exists())

    def test_students_and_anonymous_users_cannot_use_author_removal(self):
        self.assertEqual(self.remove(self.student).status_code, 403)
        self.assertEqual(self.remove(None).status_code, 401)
        self.assertTrue(Enrollment.objects.filter(pk=self.enrollment.pk).exists())

    def test_enrollment_must_belong_to_the_course_in_the_url(self):
        self.assertEqual(self.remove(self.author, enrollment=self.other_enrollment).status_code, 404)
        self.assertTrue(Enrollment.objects.filter(pk=self.other_enrollment.pk).exists())

    def test_unpublished_course_owner_can_remove_and_later_reenroll(self):
        self.assertEqual(self.remove(self.author, course=self.other_course, enrollment=self.other_enrollment).status_code, 204)
        response = self.client.post(f'/api/courses/{self.other_course.pk}/enroll_student/', {'username': 'student'}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_malformed_or_already_removed_enrollment_returns_404(self):
        self.assertEqual(self.remove(self.author).status_code, 204)
        self.assertEqual(self.remove(self.author).status_code, 404)
        self.assertEqual(self.client.delete(f'/api/courses/{self.course.pk}/enrollments/not-a-uuid/').status_code, 404)
