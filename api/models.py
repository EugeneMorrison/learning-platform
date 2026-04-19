"""
Database models for the Learning Platform

Model Relationships:
- User (1) -> (*) Course (author creates many courses)
- Course (1) -> (*) Lesson (course has many lessons)
- Lesson (1) -> (*) Block (lesson has many blocks)
- User (1) -> (*) Enrollment (*) <- (1) Course (many-to-many through Enrollment)
- User (1) -> (*) Progress (*) <- (1) Block (tracks completion)
"""

import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser


# =============================================================================
# USER MODEL (Extended Authentication)
# =============================================================================

class User(AbstractUser):
    """
    Extended Django User model with role-based access.

    WHY extend AbstractUser?
    - Django's built-in User has username, password, email, etc.
    - We just add our custom 'role' field
    - Get authentication for FREE (no need to build it!)

    Roles:
    - STUDENT: Can enroll in courses, track progress
    - AUTHOR: Can create courses, lessons, blocks
    - ADMIN: Full access
    """
    ROLE_CHOICES = [
        ('STUDENT', 'Student'),
        ('AUTHOR', 'Author'),
        ('ADMIN', 'Admin'),
    ]

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default='STUDENT',
        help_text="User's role in the platform"
    )

    class Meta:
        db_table = 'users'  # Custom table name (cleaner than auth_user)

    def __str__(self):
        return f"{self.username} ({self.role})"


# =============================================================================
# COURSE MODEL
# =============================================================================

class Course(models.Model):
    """
    Main course container.

    WHY UUID instead of auto-incrementing ID?
    - UUIDs are globally unique (no collisions)
    - Harder to guess (security)
    - Better for distributed systems
    - Won't expose "we only have 10 courses" (sequential IDs would)

    WHY ForeignKey to User?
    - Creates relationship: each course has ONE author
    - Django auto-creates reverse relation: user.authored_courses.all()
    - on_delete=CASCADE means: if user deleted, delete their courses too
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    title = models.CharField(
        max_length=255,
        help_text="Course title (e.g., 'Python Basics')"
    )

    description = models.TextField(
        blank=True,  # Optional field
        help_text="Course description/overview"
    )

    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,  # If user deleted, delete courses
        related_name='authored_courses',  # Access via: user.authored_courses.all()
        help_text="Course creator"
    )

    is_published = models.BooleanField(
        default=False,
        help_text="Only published courses visible to students"
    )

    created_at = models.DateTimeField(auto_now_add=True)  # Set once on creation
    updated_at = models.DateTimeField(auto_now=True)  # Updates on every save

    class Meta:
        db_table = 'courses'
        ordering = ['-created_at']  # Newest first by default

    def __str__(self):
        return self.title


# =============================================================================
# LESSON MODEL
# =============================================================================

class Lesson(models.Model):
    """
    Individual lesson within a course.

    WHY order_index?
    - Lessons must appear in specific order (Lesson 1, 2, 3...)
    - We can reorder without renaming
    - unique_together ensures no duplicate order within same course

    Example:
    Course: "Python Basics"
      - Lesson 1: "Variables" (order_index=1)
      - Lesson 2: "Functions" (order_index=2)
      - Lesson 3: "Classes" (order_index=3)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,  # If course deleted, delete lessons
        related_name='lessons',  # Access via: course.lessons.all()
        help_text="Parent course"
    )

    title = models.CharField(
        max_length=255,
        help_text="Lesson title (e.g., 'String Methods')"
    )

    order_index = models.IntegerField(
        help_text="Display order (1, 2, 3...)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lessons'
        ordering = ['order_index']  # Always ordered by position
        unique_together = ['course', 'order_index']  # No duplicate orders in same course

    def __str__(self):
        return f"{self.course.title} - Lesson {self.order_index}: {self.title}"


# =============================================================================
# BLOCK MODEL (THE HEART OF THE SYSTEM!)
# =============================================================================

class Block(models.Model):
    """
    Content blocks within lessons (TEXT, QUIZ, or CODE).

    WHY JSONField for content?
    - Different block types need different data structures
    - TEXT: {"html": "<p>Theory here</p>"}
    - QUIZ: {"question": "...", "options": [...], "correct_answer": 1}
    - CODE: {"prompt": "...", "starter_code": "...", "tests": [...]}
    - Flexible! Can add new fields without migrations
    - PostgreSQL has native JSON support (fast queries)

    This is the "magic" that makes the block system work!
    """

    # Block type choices
    BLOCK_TYPE_CHOICES = [
        ('TEXT', 'Text Block'),
        ('QUIZ', 'Quiz Block'),
        ('CODE', 'Code Block'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='blocks',
        help_text="Parent lesson"
    )

    type = models.CharField(
        max_length=10,
        choices=BLOCK_TYPE_CHOICES,
        help_text="Block type (TEXT/QUIZ/CODE)"
    )

    order_index = models.IntegerField(
        help_text="Display order within lesson"
    )

    content = models.JSONField(
        help_text="Block content (structure depends on type)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'blocks'
        ordering = ['order_index']
        unique_together = ['lesson', 'order_index']

    def __str__(self):
        return f"{self.lesson.title} - {self.type} Block #{self.order_index}"


# =============================================================================
# ENROLLMENT MODEL (Student <-> Course Relationship)
# =============================================================================

class Enrollment(models.Model):
    """
    Tracks which students are enrolled in which courses.

    WHY separate Enrollment model?
    - Could use ManyToManyField, but this gives more control
    - We can add enrollment_date, status, etc.
    - Easier to track "who enrolled when"
    - Can add payment info later

    Relationship: Many students can enroll in many courses
    - User (1) -> (*) Enrollment (*) <- (1) Course
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='enrollments',
        help_text="Student enrolled"
    )

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='enrollments',
        help_text="Course enrolled in"
    )

    enrolled_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When student enrolled"
    )

    class Meta:
        db_table = 'enrollments'
        unique_together = ['student', 'course']  # Can't enroll twice in same course

    def __str__(self):
        return f"{self.student.username} → {self.course.title}"


# =============================================================================
# PROGRESS MODEL (Track Student Completion)
# =============================================================================

class Progress(models.Model):
    """
    Tracks individual block completion for each student.

    WHY track at block level (not lesson level)?
    - Granular progress tracking
    - Student can resume exactly where they left off
    - Can show "5/10 blocks completed" in UI
    - Stores answers for quizzes and code submissions

    Example:
    - Student completes TEXT block → completed=True
    - Student answers QUIZ → answer={"selected": 2}, is_correct=True
    - Student submits CODE → answer={"code": "..."}, is_correct=True/False
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='progress',
        help_text="Student tracking progress"
    )

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        help_text="Lesson being tracked"
    )

    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        help_text="Specific block being tracked"
    )

    completed = models.BooleanField(
        default=False,
        help_text="Whether block is completed"
    )

    answer = models.JSONField(
        null=True,
        blank=True,
        help_text="Student's answer/submission (for QUIZ/CODE blocks)"
    )

    is_correct = models.BooleanField(
        null=True,
        blank=True,
        help_text="Whether answer was correct (for QUIZ/CODE blocks)"
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When block was completed"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'progress'
        unique_together = ['student', 'block']  # One progress record per student per block

    def __str__(self):
        status = "✓" if self.completed else "○"
        return f"{status} {self.student.username} - {self.block}"


class Message(models.Model):
    """
    Messages between teacher and student within a course.
    """
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    receiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='received_messages'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    text = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username} → {self.receiver.username}: {self.text[:50]}"
