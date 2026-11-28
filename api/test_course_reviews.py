from django.contrib.auth.models import Permission
from rest_framework.test import APITestCase
from .models import User, Course, Lesson, Block, Progress, Enrollment, CourseReview


class CourseReviewTests(APITestCase):
    def setUp(self):
        self.author = User.objects.create_user(username='author', role='AUTHOR')
        self.student = User.objects.create_user(username='student', role='STUDENT')
        self.course = Course.objects.create(title='Review course', author=self.author, is_published=True)
        self.lesson = Lesson.objects.create(course=self.course, title='Last', order_index=1)
        self.blocks = [Block.objects.create(lesson=self.lesson, type='QUIZ', order_index=i + 1, content={}) for i in range(100)]
        Enrollment.objects.create(course=self.course, student=self.student)
        self.url = f'/api/courses/{self.course.pk}/my-review/'
        self.public = f'/api/courses/{self.course.pk}/reviews/'
        self.client.force_authenticate(self.student)

    def complete(self, count=89):
        for block in self.blocks[:count]:
            Progress.objects.get_or_create(student=self.student, lesson=self.lesson, block=block, defaults={'is_correct': True})

    def submit(self, rating=5, text='Great course'):
        return self.client.put(self.url, {'rating': rating, 'text': text}, format='json')

    def moderate(self, review, status='approved'):
        return self.client.post('/api/reviews/moderation/', {'id': review['id'], 'revision': review['revision'], 'status': status}, format='json')

    def test_exact_boundary_and_required_rating(self):
        self.complete(88)
        self.assertFalse(self.client.get(self.url).data['eligible'])
        self.assertEqual(self.submit().status_code, 403)
        self.complete(89)
        self.assertTrue(self.client.get(self.url).data['eligible'])
        self.assertTrue(self.client.get(f'/api/lessons/{self.lesson.pk}/').data['course_completed'])
        self.assertEqual(len(self.client.get('/api/dashboard/').data['completed']), 1)
        for invalid in (0, 6, 2.5, None):
            self.assertEqual(self.submit(invalid).status_code, 400)
        self.assertEqual(self.client.put(self.url, {'text': 'No rating'}, format='json').status_code, 400)
        self.assertEqual(self.submit(text='').status_code, 200)

    def test_moderation_edit_reapproval_average_and_single_review(self):
        self.complete()
        review = self.submit().data
        self.assertEqual(self.client.get(self.public).data['count'], 0)
        self.client.force_authenticate(self.author)
        self.assertEqual(len(self.client.get('/api/reviews/moderation/').data), 1)
        self.assertEqual(self.moderate(review).status_code, 200)
        published = self.client.get(self.public).data
        self.assertEqual(published['average'], 5)
        self.assertEqual(published['reviews'][0]['username'], 'student')
        self.assertIsNotNone(published['reviews'][0]['published_at'])
        page = self.client.get(f'/course/{self.course.slug}/')
        self.assertContains(page, 'Great course')
        self.client.force_authenticate(self.student)
        edited = self.submit(3, '<script>alert(1)</script>').data
        self.assertEqual(CourseReview.objects.count(), 1)
        self.assertEqual(self.client.get(self.public).data['count'], 0)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.moderate(review).status_code, 409)
        self.assertEqual(self.moderate(edited, 'rejected').status_code, 200)
        self.assertIsNone(self.client.get(self.public).data['average'])
        self.client.force_authenticate(self.student)
        edited = self.submit(4, '<script>alert(1)</script>').data
        self.client.force_authenticate(self.author)
        self.assertEqual(self.moderate(edited).status_code, 200)
        self.assertEqual(self.client.get(self.public).data['average'], 4)
        self.assertContains(self.client.get(f'/course/{self.course.slug}/'), '&lt;script&gt;')

    def test_only_owner_or_assigned_admin_can_moderate(self):
        self.complete()
        review = self.submit().data
        self.assertEqual(self.moderate(review).status_code, 404)
        staff = User.objects.create_user(username='staff', is_staff=True)
        self.client.force_authenticate(staff)
        self.assertEqual(self.moderate(review).status_code, 404)
        staff.user_permissions.add(Permission.objects.get(codename='moderate_coursereview'))
        staff = User.objects.get(pk=staff.pk)
        self.client.force_authenticate(staff)
        self.assertEqual(self.moderate(review).status_code, 200)

    def test_unenrolled_and_anonymous_cannot_submit(self):
        self.complete()
        Enrollment.objects.all().delete()
        self.assertEqual(self.submit().status_code, 404)
        self.client.force_authenticate(None)
        self.assertIn(self.submit().status_code, (401, 403))
