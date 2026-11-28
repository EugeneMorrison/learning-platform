from rest_framework.test import APITestCase

from .models import Attempt, Block, Course, Enrollment, Lesson, Progress, User


class StudentDashboardTests(APITestCase):
    def setUp(self):
        self.author = User.objects.create_user(username='author', role='AUTHOR')
        self.student = User.objects.create_user(username='student', role='STUDENT')
        self.other = User.objects.create_user(username='other', role='STUDENT')
        self.client.force_authenticate(self.student)

    def course(self, title, enrolled=False, published=True):
        course = Course.objects.create(title=title, author=self.author, is_published=published)
        lesson = Lesson.objects.create(course=course, title='Lesson', order_index=1)
        block = Block.objects.create(lesson=lesson, type='QUIZ', order_index=1,
                                     content={'question': 'Q', 'options': ['A', 'B'], 'correct_answer': 0})
        if enrolled:
            Enrollment.objects.create(student=self.student, course=course)
        return course, lesson, block

    def dashboard(self):
        response = self.client.get('/api/dashboard/')
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_sections_resume_visits_and_activity_order(self):
        first, lesson, block = self.course('First', enrolled=True)
        second, _, _ = self.course('Second', enrolled=True)
        later = Lesson.objects.create(course=first, title='Later', order_index=2)
        self.assertEqual(self.dashboard()['in_progress'][0]['id'], str(second.pk))
        self.assertEqual(self.client.get(f'/api/lessons/{later.pk}/').status_code, 200)
        result = self.dashboard()['in_progress']
        self.assertEqual(result[0]['id'], str(first.pk))
        self.assertEqual(result[0]['last_lesson'], str(later.pk))
        self.assertEqual(result[0]['completion_percentage'], 0)
        Attempt.objects.create(student=self.student, block=block, is_correct=False)
        self.assertEqual(self.dashboard()['in_progress'][0]['last_lesson'], str(lesson.pk))
        Progress.objects.create(student=self.student, lesson=lesson, block=block, is_correct=True)
        result = self.dashboard()
        self.assertEqual([c['id'] for c in result['completed']], [str(first.pk)])
        self.assertEqual(result['completed'][0]['completion_percentage'], 100)
        self.assertEqual(self.client.get(f'/api/lessons/{lesson.pk}/').status_code, 200)
        response = self.client.post('/api/progress/submit/', {'block': str(block.pk), 'answer': {'selected': 1}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.dashboard()['completed']), 1)
        enrollment = Enrollment.objects.get(student=self.student, course=first)
        self.assertEqual(enrollment.last_lesson_id, lesson.pk)
        self.assertIsNotNone(enrollment.last_activity_at)

    def test_every_assignment_is_required_and_percentage_is_partial(self):
        course, lesson, block = self.course('Mixed tasks', enrolled=True)
        other = Block.objects.create(lesson=lesson, type='CODE', order_index=2, content={})
        Block.objects.create(lesson=lesson, type='TEXT', order_index=3, content={})
        Progress.objects.create(student=self.student, lesson=lesson, block=block, is_correct=True)
        result = self.dashboard()
        self.assertEqual(result['in_progress'][0]['completion_percentage'], 50)
        self.assertEqual(result['completed'], [])
        Progress.objects.create(student=self.student, lesson=lesson, block=other, is_correct=True)
        self.assertEqual(self.dashboard()['completed'][0]['id'], str(course.pk))

    def test_popularity_followups_and_exclusions(self):
        first, lesson, block = self.course('Strings 1', enrolled=True)
        sequel, _, _ = self.course('Strings 2')
        popular, _, _ = self.course('Popular')
        hidden, _, _ = self.course('Hidden', published=False)
        first.recommended_courses.set([sequel, hidden])
        Enrollment.objects.create(student=self.other, course=popular)
        self.assertEqual(self.dashboard()['recommended'][0]['id'], str(popular.pk))
        Progress.objects.create(student=self.student, lesson=lesson, block=block, is_correct=True)
        result = self.dashboard()['recommended']
        self.assertEqual([c['id'] for c in result], [str(sequel.pk), str(popular.pk)])
        Enrollment.objects.filter(student=self.student, course=first).delete()
        self.assertNotIn(str(first.pk), [c['id'] for c in self.dashboard()['recommended']])
        Enrollment.objects.create(student=self.student, course=sequel)
        self.assertEqual([c['id'] for c in self.dashboard()['recommended']], [str(popular.pk)])

    def test_empty_and_new_student_popularity(self):
        self.assertEqual(self.dashboard(), {'in_progress': [], 'completed': [], 'recommended': []})
        course, _, _ = self.course('Popular')
        Enrollment.objects.create(student=self.other, course=course)
        result = self.dashboard()['recommended'][0]
        self.assertEqual(result['id'], str(course.pk))
        self.assertEqual(result['price'], '0.00')
        self.assertIn('level', result)

    def test_owner_can_configure_relationships(self):
        course, _, _ = self.course('First')
        sequel, _, _ = self.course('Second')
        url = f'/api/courses/{course.pk}/'
        self.assertEqual(self.client.patch(url, {'recommended_courses': [str(sequel.pk)]}, format='json').status_code, 403)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.patch(url, {'recommended_courses': [str(sequel.pk)]}, format='json').status_code, 200)
        self.assertEqual(list(course.recommended_courses.all()), [sequel])
        self.assertEqual(self.client.patch(url, {'recommended_courses': [str(course.pk)]}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'recommended_courses': []}, format='json').status_code, 200)
        self.assertFalse(course.recommended_courses.exists())
        outsider = User.objects.create_user(username='outsider', role='AUTHOR')
        private = Course.objects.create(title='Private', author=outsider)
        self.assertEqual(self.client.patch(url, {'recommended_courses': [str(private.pk)]}, format='json').status_code, 400)

    def test_other_students_do_not_affect_resume_or_completion(self):
        course, lesson, block = self.course('Course', enrolled=True)
        Progress.objects.create(student=self.other, lesson=lesson, block=block, is_correct=True)
        self.assertEqual(self.dashboard()['in_progress'][0]['completion_percentage'], 0)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get('/api/dashboard/').status_code, (401, 403))

    def test_deleted_last_lesson_falls_back_and_no_tasks_match_viewer(self):
        course, lesson, _ = self.course('Course', enrolled=True)
        extra = Lesson.objects.create(course=course, title='Extra', order_index=2)
        self.client.get(f'/api/lessons/{extra.pk}/')
        extra.delete()
        self.assertEqual(self.dashboard()['in_progress'][0]['last_lesson'], str(lesson.pk))
        lesson.blocks.all().delete()
        self.assertEqual(self.dashboard()['completed'][0]['completion_percentage'], 100)
