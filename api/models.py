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
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from slugify import slugify

from .block_content import TASK_TYPES
from .covers import shrink_cover


# =============================================================================
# READ-ACCESS RULES (one place; every view that reads courses/lessons/blocks uses these)
# =============================================================================
#
# Coursera-style: the course page and syllabus are public (Django pages);
# lesson CONTENT is not.
# - Course metadata: published courses for everyone; unpublished only for their
#   author and enrolled students.
# - Lessons and blocks: own courses (author) ∪ enrolled courses (student).
#   Anonymous users get nothing, free or paid.
# Views must return 404 (not 403) for anything outside these querysets.

class CourseQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Courses whose metadata (title, description, price) the user may read:
        published ∪ own (author) ∪ enrolled (a teacher may enrol students before
        publishing)."""
        if not user.is_authenticated:
            return self.filter(is_published=True)
        return self.filter(
            models.Q(is_published=True)
            | models.Q(author=user)
            | models.Q(enrollments__student=user)
        ).distinct()

    def with_content_access(self, user):
        """Courses whose lessons and blocks the user may read: own ∪ enrolled."""
        if not user.is_authenticated:
            return self.none()
        return self.filter(
            models.Q(author=user) | models.Q(enrollments__student=user)
        ).distinct()


class LessonQuerySet(models.QuerySet):
    def visible_to(self, user):
        return self.filter(
            course__in=Course.objects.with_content_access(user).values('pk'))


class BlockQuerySet(models.QuerySet):
    def visible_to(self, user):
        return self.filter(
            lesson__course__in=Course.objects.with_content_access(user).values('pk'))


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

    # --- Sales / landing-page fields -------------------------------------
    slug = models.SlugField(
        max_length=255,
        unique=True,
        blank=True,  # Left blank in admin → auto-filled (transliterated) in save()
        help_text="URL identifier; auto-generated from the title (transliterated) when left blank"
    )

    tagline = models.CharField(
        max_length=200,
        blank=True,
        help_text="Short marketing subtitle shown on the course card"
    )

    tag = models.CharField(
        max_length=24,
        blank=True,
        help_text="Optional chip on the card cover, e.g. «Новый» or «Хит»; shown as typed on /en/ too"
    )

    cover = models.ImageField(
        upload_to="covers/",
        blank=True,
        help_text="Cover for the course cards (4:3) and the course page. Recommended "
                  "800×600; your own artwork only. Larger images are shrunk to 1200 px wide "
                  "and saved as WebP (stored under MEDIA_ROOT/covers/)"
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Price in rubles (0 = free)"
    )

    old_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Original price for a strikethrough discount; leave empty if none"
    )

    sort_order = models.PositiveIntegerField(
        default=0,
        help_text="Manual ordering on the landing page (lower = earlier)"
    )

    # Difficulty, chosen by the author (React course page / dashboard form, or
    # the admin). Optional: no level = «Не указан». The /courses/ catalog
    # filters and sorts by it, in this order (LEVEL_CHOICES order = difficulty).
    LEVEL_BEGINNER = 'BEGINNER'
    LEVEL_INTERMEDIATE = 'INTERMEDIATE'
    LEVEL_ADVANCED = 'ADVANCED'
    LEVEL_CHOICES = [
        (LEVEL_BEGINNER, _('Начальный')),
        (LEVEL_INTERMEDIATE, _('Средний')),
        (LEVEL_ADVANCED, _('Продвинутый')),
    ]

    level = models.CharField(
        max_length=12,
        choices=LEVEL_CHOICES,
        null=True,
        blank=True,
        default=None,
        help_text="Difficulty; leave empty if not specified"
    )

    stepik_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        unique=True,
        help_text="Linked Stepik course id, if the course also lives on Stepik"
    )
    # ---------------------------------------------------------------------

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

    objects = CourseQuerySet.as_manager()

    class Meta:
        db_table = 'courses'
        ordering = ['sort_order', '-created_at']  # Manual order first, then newest

    def __str__(self):
        return self.title

    @property
    def is_free(self):
        """True when the course costs nothing. Computed, NOT a DB column."""
        return self.price == 0

    def save(self, *args, **kwargs):
        """Fill a unique slug from the (transliterated) title when left blank.

        Shrink a newly assigned cover (api/covers.py). Not committed = a new file
        that isn't in storage yet (an upload); a cover loaded from the database
        is committed, so saves that don't change it never re-process it.

        A replaced or removed cover's old file is deleted (any path: course page,
        admin, code), so media/covers/ doesn't collect leftovers. The stored name
        is read from the database right before saving, rather than remembered
        from loading, so it is never stale."""
        if not self.slug:
            self.slug = self._generate_unique_slug()

        update_fields = kwargs.get('update_fields')
        old_cover = ''
        if not self._state.adding and (update_fields is None or 'cover' in update_fields):
            old_cover = Course.objects.filter(pk=self.pk).values_list('cover', flat=True).first() or ''

        if self.cover and not self.cover._committed:
            self.cover = shrink_cover(self.cover.file)  # stored by FileField as usual
        super().save(*args, **kwargs)

        if old_cover and old_cover != self.cover.name:
            self._delete_cover_file(old_cover)

    @classmethod
    def _delete_cover_file(cls, name):
        """Delete a cover file once the save is committed (a rolled-back save
        keeps it), unless another course still points to the same file."""
        storage = cls._meta.get_field('cover').storage

        def delete():
            if not cls.objects.filter(cover=name).exists():
                storage.delete(name)  # a file that's already gone is fine

        transaction.on_commit(delete)

    def _generate_unique_slug(self):
        """Transliterate the title to a slug, falling back to 'course' for
        titles that transliterate to nothing, and dedupe with a -N suffix.
        Caps the base at 250 chars so the suffix fits SlugField's 255 limit."""
        base = (slugify(self.title or '')[:250].rstrip('-')) or 'course'
        slug = base
        n = 2
        while Course.objects.exclude(pk=self.pk).filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug


@receiver(post_delete, sender=Course)
def delete_cover_with_course(sender, instance, **kwargs):
    """A deleted course takes its cover file along (after the commit, and not
    while another course points to it: Course._delete_cover_file). A signal, not
    Course.delete(): the admin's bulk delete and cascades (a deleted author)
    don't call delete() on each course, but do send post_delete."""
    if instance.cover:
        Course._delete_cover_file(instance.cover.name)


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

    objects = LessonQuerySet.as_manager()

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
      Multiple answers: add "multiple_answers": true and "correct_answers": [0, 2]
      instead of "correct_answer".
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
        ('FILL', 'Fill-in-the-blanks Block'),
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

    objects = BlockQuerySet.as_manager()

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

    attempts = models.IntegerField(
        default=0,
        help_text="How many times the student submitted this block (1 = solved first try)"
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


class Attempt(models.Model):
    """
    Full submission history. Progress holds only the latest answer + a counter,
    so this table records every individual submission so the teacher can review
    the student's path (wrong attempts, retries, the actual code they wrote).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='attempts',
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name='attempts',
    )
    answer = models.JSONField(
        null=True,
        blank=True,
        help_text="The submitted answer payload (e.g. {'code': '...'} or {'selected': 2})"
    )
    is_correct = models.BooleanField(
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'attempts'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['student', 'block', 'created_at']),
        ]

    def __str__(self):
        mark = "✓" if self.is_correct else ("✗" if self.is_correct is False else "·")
        return f"{mark} {self.student.username} - {self.block} @ {self.created_at:%Y-%m-%d %H:%M:%S}"


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
    # «Задать вопрос» (POST /api/questions/): the task the question is about and
    # a snapshot of it and of the student's work at that moment (api/questions.py).
    # Plain chat messages have neither.
    block = models.ForeignKey(
        Block,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='questions'
    )
    context = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at', 'id']  # the id: messages saved in the same instant
        indexes = [
            # Unread counts: GET /api/messages/unread/ and POST /api/messages/read/.
            models.Index(fields=['receiver', 'is_read'], name='messages_receiver_unread_idx'),
        ]

    def __str__(self):
        return f"{self.sender.username} → {self.receiver.username}: {self.text[:50]}"


# =============================================================================
# DISCUSSIONS (public threads per task block; api/discussions.py)
# =============================================================================

class ThreadQuerySet(models.QuerySet):
    def visible_to(self, user):
        """
        Threads the user may read, and so reply to (the one rule; every
        discussion endpoint goes through it):
        - only on task blocks of courses the user has content access to
          (own ∪ enrolled, as BlockQuerySet.visible_to);
        - the course author sees all of them;
        - anyone else sees all of them once they have solved the block
          (Progress.is_correct, which stays True), before that only the pinned
          threads and the ones they started themselves.
        """
        if not user.is_authenticated:
            return self.none()
        solved = Progress.objects.filter(student=user, block=models.OuterRef('block'), is_correct=True)
        return self.filter(
            block__type__in=TASK_TYPES,
            block__lesson__course__in=Course.objects.with_content_access(user).values('pk'),
        ).filter(
            models.Q(block__lesson__course__author=user)
            | models.Q(is_pinned=True)
            | models.Q(starter=user)
            | models.Exists(solved)
        )


class Thread(models.Model):
    """A discussion about one task block. Its text is its first Comment."""
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='threads')
    starter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='started_threads')
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    is_pinned = models.BooleanField(default=False, help_text="Pinned by the course author: shown first, and to everyone")

    objects = ThreadQuerySet.as_manager()

    class Meta:
        db_table = 'threads'
        # Pinned first, resolved after the open ones, newest first.
        ordering = ['-is_pinned', 'is_resolved', '-created_at', '-id']

    def __str__(self):
        return f"Thread #{self.pk} on {self.block} by {self.starter.username}"


class Comment(models.Model):
    """
    One post in a thread (the first one opens it). Plain text, never rendered
    as HTML. Deleted by the course author softly: the row stays (the thread
    keeps its shape, the author can still read it); everyone else gets no text.
    """
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='discussion_comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    class Meta:
        db_table = 'comments'
        ordering = ['created_at', 'id']
        indexes = [
            # The rate limit: the user's latest comment (api/discussions.py).
            models.Index(fields=['user', 'created_at'], name='comments_user_created_idx'),
        ]

    def __str__(self):
        return f"{self.user.username} in thread #{self.thread_id}: {self.text[:50]}"


class DiscussionBan(models.Model):
    """
    A course author has stopped a user posting in the discussions of all her
    courses (per author, not per course). The user can still read them.
    """
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='discussion_bans_given')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='discussion_bans')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'discussion_bans'
        unique_together = ['author', 'user']
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"{self.author.username} banned {self.user.username}"


class CommentReport(models.Model):
    """
    A student flags a comment for the course author. Open until the author
    dismisses it or deletes the comment. One per comment and reporter.
    """
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comment_reports')
    created_at = models.DateTimeField(auto_now_add=True)
    is_dismissed = models.BooleanField(default=False)

    class Meta:
        db_table = 'comment_reports'
        unique_together = ['comment', 'reporter']
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.reporter.username} reported comment #{self.comment_id}"


# =============================================================================
# LANDING PAGE CONTENT (managed in the Django admin)
# =============================================================================

def _localized(ru, en, lang):
    """English text on /en/ when filled in, otherwise the Russian text."""
    if (lang or '').startswith('en') and en.strip():
        return en
    return ru


class AuthorProfile(models.Model):
    """
    The course author. Intended as a single row (the admin allows only one).
    Not shown on the public pages at the moment: "Обо мне" (/about/) keeps its
    text in the template.
    """
    name = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True, help_text="Name in English; leave empty to show the Russian name on /en/")
    photo = models.ImageField(upload_to='author/', blank=True)
    bio_ru = models.TextField(blank=True, help_text="Bio in Russian (plain text; blank lines start paragraphs)")
    bio_en = models.TextField(blank=True, help_text="Bio in English; leave empty to show the Russian text on /en/")
    stepik_url = models.URLField(blank=True, help_text="Author's Stepik profile (optional)")

    class Meta:
        db_table = 'author_profile'
        verbose_name = 'author profile'

    def __str__(self):
        return self.name

    def name_for(self, lang):
        return _localized(self.name, self.name_en, lang)

    def bio_for(self, lang):
        return _localized(self.bio_ru, self.bio_en, lang)


class Review(models.Model):
    """A student review for the landing page's "Отзывы" section (published ones only)."""
    student_name = models.CharField(max_length=200)
    text_ru = models.TextField(help_text="Review text in Russian")
    text_en = models.TextField(blank=True, help_text="English translation; leave empty to show the Russian text on /en/")
    course = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviews',
        help_text="Course the review is about (optional)",
    )
    source = models.CharField(max_length=100, blank=True, help_text='Where it was posted, e.g. "Stepik"')
    source_url = models.URLField(blank=True, help_text="Link to the original review (optional)")
    is_published = models.BooleanField(default=False, help_text="Only published reviews appear on the site")
    order = models.PositiveIntegerField(default=0, help_text="Order on the landing page (lower = earlier)")

    class Meta:
        db_table = 'reviews'
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.student_name}: {self.text_ru[:50]}"

    def text_for(self, lang):
        return _localized(self.text_ru, self.text_en, lang)
