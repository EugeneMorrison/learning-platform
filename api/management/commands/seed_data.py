from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from api.models import Course, Lesson, Block, Enrollment
import uuid

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed database with sample data'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding database...')

        # Create users
        author, _ = User.objects.get_or_create(
            username='john',
            defaults={'role': 'AUTHOR', 'email': 'john@example.com'}
        )
        author.set_password('password123')
        author.save()

        student, _ = User.objects.get_or_create(
            username='alice',
            defaults={'role': 'STUDENT', 'email': 'alice@example.com'}
        )
        student.set_password('password123')
        student.save()

        # Create course
        course, created = Course.objects.get_or_create(
            title='Python Basics',
            defaults={
                'description': 'Learn Python from scratch',
                'author': author,
                'is_published': True
            }
        )

        if created:
            # Create lesson
            lesson = Lesson.objects.create(
                course=course,
                title='String Methods',
                order_index=1
            )

            # Create TEXT block
            Block.objects.create(
                lesson=lesson,
                type='TEXT',
                order_index=1,
                content={
                    "html": "<h2>Introduction to Strings</h2><p>Strings are sequences of characters...</p>"
                }
            )

            # Create QUIZ block
            Block.objects.create(
                lesson=lesson,
                type='QUIZ',
                order_index=2,
                content={
                    "question": "What does .startswith() return?",
                    "options": ["String", "Boolean", "Number", "None"],
                    "correct_answer": 1,
                    "explanation": "It returns True or False"
                }
            )

            # Create CODE block
            Block.objects.create(
                lesson=lesson,
                type='CODE',
                order_index=3,
                content={
                    "prompt": "Check if text starts with 'Hello'",
                    "starter_code": "text = 'Hello World'\n# Your code here\nresult = ",
                    "solution": "text.startswith('Hello')",
                    "tests": ["assert result == True"]
                }
            )

            # Enroll student
            Enrollment.objects.create(
                student=student,
                course=course
            )

        self.stdout.write(self.style.SUCCESS('✅ Database seeded successfully!'))
        self.stdout.write(f'Users: john (author), alice (student)')
        self.stdout.write(f'Course: {course.title}')
        self.stdout.write(f'Password for both: password123')