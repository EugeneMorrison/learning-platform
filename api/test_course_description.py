from rest_framework.test import APITestCase

from .models import Course, Enrollment, User


class CourseDescriptionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author', role='AUTHOR')
        cls.other = User.objects.create_user(username='other', role='AUTHOR')
        cls.student = User.objects.create_user(username='student', role='STUDENT')
        cls.course = Course.objects.create(title='Physics', author=cls.author, is_published=True)
        Enrollment.objects.create(student=cls.student, course=cls.course)

    def test_owner_can_add_edit_and_clear_description(self):
        self.client.force_authenticate(self.author)
        url = f'/api/courses/{self.course.id}/'
        for description in ['Course overview\nSecond line', 'Updated overview', '']:
            response = self.client.patch(url, {'description': description}, format='json')
            self.assertEqual(response.status_code, 200)
            self.course.refresh_from_db()
            self.assertEqual(self.course.description, description)
            self.assertEqual(self.client.get(url).data['description'], description)
            self.assertEqual(self.course.title, 'Physics')

    def test_other_author_and_student_cannot_change_description(self):
        for user in (self.other, self.student):
            self.client.force_authenticate(user)
            response = self.client.patch(f'/api/courses/{self.course.id}/',
                                         {'description': 'Changed'}, format='json')
            self.assertEqual(response.status_code, 403)
        self.course.refresh_from_db()
        self.assertEqual(self.course.description, '')
