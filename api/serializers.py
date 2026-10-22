"""
Serializers for the Learning Platform API

Serializers convert between:
- Python objects (models) → JSON (for API responses)
- JSON (from API requests) → Python objects (for database)

"""

from django.utils.translation import gettext
from rest_framework import serializers
from .block_content import FILL_GAP_RE, TASK_TYPES, feedback, student_content
from .models import User, Course, Lesson, Block, Enrollment, Progress, Message, Thread, Comment


# =============================================================================
# USER SERIALIZER
# =============================================================================

class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for User model.

    Why ModelSerializer?
    - Automatically creates fields based on the model
    - Handles validation
    - Provides create() and update() methods
    - Much less code than writing manually!
    """

    # Add computed fields (not in database, but useful for API)
    course_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'role',
            'first_name',
            'last_name',
            'date_joined',
            'course_count'  # How many courses this user authored
        ]
        # role is read-only: users never set their own role through the API
        # (public registration creates students; authors/admins come from the admin).
        read_only_fields = ['id', 'date_joined', 'role']
        extra_kwargs = {
            'password': {'write_only': True}  # Never return password in API!
        }

    def get_course_count(self, obj):
        """Count how many courses this user has authored"""
        return obj.authored_courses.count()


# =============================================================================
# COURSE SERIALIZER
# =============================================================================

TITLE_ERRORS = {
    'blank': 'Название не может быть пустым.',
    'null': 'Название не может быть пустым.',
    'max_length': 'Название не длиннее 255 символов.',
}


class CourseSerializer(serializers.ModelSerializer):
    """
    Serializer for Course model.

    Includes extra computed fields:
    - author_name: Name of the author (instead of just ID)
    - lesson_count: How many lessons in this course
    """

    # Computed fields
    author_name = serializers.CharField(source='author.username', read_only=True)
    lesson_count = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = [
            'id',
            'title',
            'description',
            'author',
            'author_name',  # Extra: author's username
            'is_published',
            'level',  # BEGINNER / INTERMEDIATE / ADVANCED, or null (not specified)
            'lesson_count',  # Extra: number of lessons
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'author', 'created_at', 'updated_at']
        extra_kwargs = {'title': {'error_messages': TITLE_ERRORS}}

    def validate_level(self, value):
        """«Не указан» is stored as NULL, whether the client sends null or ''."""
        return value or None

    def get_lesson_count(self, obj):
        """Count lessons in this course"""
        return obj.lessons.count()


# =============================================================================
# LESSON SERIALIZER
# =============================================================================

class LessonSerializer(serializers.ModelSerializer):
    """
    Serializer for Lesson model.

    Includes:
    - course_title: Name of the parent course
    - block_count: How many blocks in this lesson
    """

    course_title = serializers.CharField(source='course.title', read_only=True)
    block_count = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            'id',
            'course',
            'course_title',  # Extra: parent course name
            'title',
            'order_index',
            'block_count',  # Extra: number of blocks
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {'title': {'error_messages': TITLE_ERRORS}}

    def get_block_count(self, obj):
        """Count blocks in this lesson"""
        return obj.blocks.count()

    def validate_title(self, value):
        """Validate lesson title."""
        if not value or not value.strip():
            raise serializers.ValidationError(gettext('Название не может быть пустым.'))

        if len(value.strip()) < 2:
            raise serializers.ValidationError(gettext('Название должно быть не короче 2 символов.'))

        return value.strip()

    def validate_order_index(self, value):
        """Validate order_index is positive."""
        if value < 1:
            raise serializers.ValidationError("Order index must be at least 1.")

        return value

    def validate(self, data):
        """
        Check for duplicate order_index in same course.
        """
        course = data.get('course')
        order_index = data.get('order_index')

        if course and order_index:
            # Check for existing lesson with same order in same course
            query = Lesson.objects.filter(course=course, order_index=order_index)

            # Exclude current instance if updating
            if self.instance:
                query = query.exclude(pk=self.instance.pk)

            if query.exists():
                raise serializers.ValidationError({
                    'order_index': f'A lesson with order {order_index} already exists in this course.'
                })

        return data


def course_lesson_ids_in_order(course_id):
    """The course's lesson ids in reading order (by order_index; gaps don't
    matter). A lesson's position is its index here + 1: the single source for
    lesson_position (lesson viewer) and position (GET /api/lessons/outline/)."""
    return list(
        Lesson.objects.filter(course_id=course_id)
        .order_by('order_index')
        .values_list('id', flat=True)
    )


class LessonViewerSerializer(LessonSerializer):
    """
    A single lesson for the lesson viewer (GET /api/lessons/{id}/).

    Adds (read-only; only the detail response carries them, so lesson lists
    don't pay extra queries per lesson):
    - lesson_position / lesson_count: "Урок N из M"; N is the place in the
      course's ordered lessons (1-based), not order_index.
    - next_lesson_id: the next lesson of the same course, null on the last one.
    - course_completed: the requesting user has solved every task (QUIZ, CODE,
      FILL) in the course; a course without tasks counts as completed.
    """

    lesson_position = serializers.SerializerMethodField()
    lesson_count = serializers.SerializerMethodField()
    next_lesson_id = serializers.SerializerMethodField()
    course_completed = serializers.SerializerMethodField()

    class Meta(LessonSerializer.Meta):
        fields = LessonSerializer.Meta.fields + [
            'lesson_position', 'lesson_count', 'next_lesson_id', 'course_completed',
        ]

    def _ordered_ids(self, obj):
        # One query for the three navigation fields.
        if getattr(self, '_ids_course', None) != obj.course_id:
            self._ids_course = obj.course_id
            self._ids = course_lesson_ids_in_order(obj.course_id)
        return self._ids

    def get_lesson_position(self, obj):
        return self._ordered_ids(obj).index(obj.id) + 1

    def get_lesson_count(self, obj):
        return len(self._ordered_ids(obj))

    def get_next_lesson_id(self, obj):
        ids = self._ordered_ids(obj)
        position = ids.index(obj.id) + 1
        return ids[position] if position < len(ids) else None

    def get_course_completed(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        tasks = Block.objects.filter(lesson__course_id=obj.course_id, type__in=TASK_TYPES)
        # One Progress row per student per block (unique_together).
        solved = Progress.objects.filter(student=user, block__in=tasks, is_correct=True).count()
        return solved == tasks.count()


# =============================================================================
# BLOCK SERIALIZER
# =============================================================================

class BlockSerializer(serializers.ModelSerializer):
    """
    Serializer for Block model.

    The content field is JSONField - Django automatically handles conversion!

    Two views of `content`, chosen per block here (the one place that decides):
    - the course's author gets the full content (editor, importer round-trips);
    - everyone else gets block_content.student_content(): no solution, no
      hidden tests, no correct answers, no explanations.
    Without a request in the serializer context the student view is used.
    """

    lesson_title = serializers.CharField(source='lesson.title', read_only=True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._is_course_author(instance):
            data['content'] = student_content(instance.type, instance.content)
        return data

    def _is_course_author(self, block):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated
                    and block.lesson.course.author_id == user.id)

    class Meta:
        model = Block
        fields = [
            'id',
            'lesson',
            'lesson_title',  # Extra: parent lesson name
            'type',
            'order_index',
            'content',  # JSONField - automatic JSON handling!
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        """
        Content must fit the block type. Runs whenever type or content changes,
        using the stored value for whichever one the request leaves out: a PATCH
        with only "content" is checked against the block's type, a PATCH with
        only "type" checks the stored content. (Before, a PATCH without "type"
        skipped this, and e.g. a string as content broke the lesson for
        students.) Errors stay under "content". A PATCH of order_index alone
        (the editor's up/down) isn't affected.
        """
        attrs = super().validate(attrs)
        if 'type' in attrs or 'content' in attrs:
            block_type = attrs.get('type', getattr(self.instance, 'type', None))
            content = attrs.get('content', getattr(self.instance, 'content', None))
            error = block_content_error(block_type, content)
            if error:
                raise serializers.ValidationError({'content': [error]})
        return attrs


def block_content_error(block_type, value):
    """Why content doesn't fit the block type, or None when it does."""
    if not isinstance(value, dict):
        return "content must be a JSON object"

    if block_type == 'TEXT':
        if 'html' not in value:
            return "TEXT blocks must have 'html' field in content"

    elif block_type == 'QUIZ':
        for field in ['question', 'options', 'correct_answer']:
            if field not in value:
                return f"QUIZ blocks must have '{field}' field in content"
        # Optional: show the options to students in random order (missing = true).
        if 'shuffle_options' in value and not isinstance(value['shuffle_options'], bool):
            return "QUIZ 'shuffle_options' must be true or false"

    elif block_type == 'CODE':
        for field in ['prompt', 'starter_code']:
            if field not in value:
                return f"CODE blocks must have '{field}' field in content"
        # Optional hidden code run before / after the student's.
        for field in ['header', 'footer']:
            if field in value and not isinstance(value[field], str):
                return f"CODE '{field}' must be a string"
        # Optional per-test flag: shown to students or hidden.
        for test in value.get('tests') or []:
            if isinstance(test, dict) and 'visible' in test and not isinstance(test['visible'], bool):
                return "CODE test 'visible' must be true or false"

    elif block_type == 'FILL':
        # Fill-in-the-blanks: a code/text template with {{answer}} markers.
        template = value.get('template')
        if not template:
            return "FILL blocks must have a non-empty 'template' field in content"
        blanks = FILL_GAP_RE.findall(template)
        if not blanks or not any(b.strip() for b in blanks):
            return "FILL template must contain at least one blank with an answer, e.g. print({{8}})"

    return None


# =============================================================================
# ENROLLMENT SERIALIZER
# =============================================================================

class EnrollmentSerializer(serializers.ModelSerializer):
    """
    Serializer for Enrollment model.

    Shows which student is enrolled in which course.
    """

    student_name = serializers.CharField(source='student.username', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            'id',
            'student',
            'student_name',  # Extra: student's username
            'course',
            'course_title',  # Extra: course title
            'enrolled_at'
        ]
        read_only_fields = ['id', 'enrolled_at', 'student']


# =============================================================================
# PROGRESS SERIALIZER
# =============================================================================

class ProgressSerializer(serializers.ModelSerializer):
    """
    Serializer for Progress model.

    Tracks student completion of individual blocks.
    """

    student_name = serializers.CharField(source='student.username', read_only=True)
    lesson_title = serializers.CharField(source='lesson.title', read_only=True)
    block_type = serializers.CharField(source='block.type', read_only=True)
    # Server-side feedback on the student's own saved answer (see
    # block_content.feedback): explanation only when correct; FILL gap results.
    feedback = serializers.SerializerMethodField()

    def get_feedback(self, obj):
        return feedback(obj.block.type, obj.block.content, obj.answer, obj.is_correct)

    class Meta:
        model = Progress
        fields = [
            'id',
            'student',
            'student_name',  # Extra: who is this?
            'lesson',
            'lesson_title',  # Extra: which lesson?
            'block',
            'block_type',  # Extra: what kind of block?
            'completed',
            'answer',  # Student's answer (JSON)
            'is_correct',
            'feedback',  # Extra: explanation (when correct), FILL gap results
            'completed_at',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'student', 'is_correct', 'completed_at', 'created_at', 'updated_at']


# =============================================================================
# NESTED SERIALIZERS (For detailed views)
# =============================================================================

class CourseDetailSerializer(serializers.ModelSerializer):
    """
    Detailed course view with all lessons included.

    When you GET /api/courses/123/, you'll see:
    - Course info
    - List of all lessons in the course

    This is called "nested serialization"
    """

    lessons = LessonSerializer(many=True, read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = Course
        fields = [
            'id',
            'title',
            'description',
            'author',
            'author_name',
            'is_published',
            'lessons',  # Nested: all lessons in this course!
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class LessonDetailSerializer(serializers.ModelSerializer):
    """
    Detailed lesson view with all blocks included.

    When you GET /api/lessons/123/, you'll see:
    - Lesson info
    - List of all blocks in the lesson
    """

    blocks = BlockSerializer(many=True, read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)

    class Meta:
        model = Lesson
        fields = [
            'id',
            'course',
            'course_title',
            'title',
            'order_index',
            'blocks',  # Nested: all blocks in this lesson!
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class MessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    # Full name when the user has one, else the username (question cards).
    sender_name = serializers.SerializerMethodField()
    receiver_username = serializers.CharField(source='receiver.username', read_only=True)

    def get_sender_name(self, obj):
        return obj.sender.get_full_name() or obj.sender.username

    class Meta:
        model = Message
        fields = [
            'id',
            'sender',
            'sender_username',
            'sender_name',
            'receiver',
            'receiver_username',
            'course',
            'text',
            'is_read',
            'created_at',
            'block',    # «Задать вопрос» only (else null): the task asked about
            'context',  # its snapshot (api/questions.py)
        ]
        read_only_fields = ['id', 'created_at', 'sender', 'block', 'context']


def display_name(user):
    """Full name when the user has one, else the username."""
    return user.get_full_name() or user.username


class DiscussionViewerMixin:
    """Discussion serializers answer per viewer: context needs `request` and
    `course_author_id` (the author of the block's course); views.
    discussion_context also adds what the viewer's flags need: `reported_ids`
    (comments the viewer reported), `report_counts` and `banned_ids` (course
    author only)."""

    def viewer_id(self):
        return self.context['request'].user.id

    def viewer_is_author(self):
        return self.viewer_id() == self.context['course_author_id']


class CommentSerializer(DiscussionViewerMixin, serializers.ModelSerializer):
    """A discussion post. A deleted one keeps its place, but its text goes
    only to the course author (text: null for everyone else). Moderation:
    the viewer's own report (reported, can_report); for the course author
    only, open reports (report_count) and whether its writer is banned
    (user_is_banned, can_ban), null for everyone else."""
    user_name = serializers.SerializerMethodField()
    is_course_author = serializers.SerializerMethodField()
    text = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    reported = serializers.SerializerMethodField()
    can_report = serializers.SerializerMethodField()
    report_count = serializers.SerializerMethodField()
    user_is_banned = serializers.SerializerMethodField()
    can_ban = serializers.SerializerMethodField()

    def get_reported(self, obj):
        return obj.id in self.context.get('reported_ids', ())

    def get_can_report(self, obj):
        return not (self.viewer_is_author() or obj.is_deleted or obj.user_id == self.viewer_id()
                    or obj.user_id == self.context['course_author_id'] or self.get_reported(obj))

    def get_report_count(self, obj):
        return self.context.get('report_counts', {}).get(obj.id, 0) if self.viewer_is_author() else None

    def get_user_is_banned(self, obj):
        return obj.user_id in self.context.get('banned_ids', ()) if self.viewer_is_author() else None

    def get_can_ban(self, obj):
        return self.viewer_is_author() and obj.user_id != self.context['course_author_id']

    def get_user_name(self, obj):
        return display_name(obj.user)

    def get_is_course_author(self, obj):
        return obj.user_id == self.context['course_author_id']

    def get_text(self, obj):
        if obj.is_deleted and not self.viewer_is_author():
            return None
        return obj.text

    def get_can_delete(self, obj):
        return self.viewer_is_author() and not obj.is_deleted

    class Meta:
        model = Comment
        fields = ['id', 'thread', 'user', 'user_name', 'is_course_author', 'text', 'is_deleted',
                  'created_at', 'can_delete', 'reported', 'can_report', 'report_count',
                  'user_is_banned', 'can_ban']
        read_only_fields = fields


class ThreadSerializer(DiscussionViewerMixin, serializers.ModelSerializer):
    """A thread with all its comments (the first one opened it) and what the
    viewer may do with it (api/discussions.py)."""
    starter_name = serializers.SerializerMethodField()
    resolved_by_name = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)
    can_resolve = serializers.SerializerMethodField()
    can_pin = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    def get_starter_name(self, obj):
        return display_name(obj.starter)

    def get_resolved_by_name(self, obj):
        return display_name(obj.resolved_by) if obj.resolved_by else None

    def get_can_resolve(self, obj):
        return self.viewer_is_author() or obj.starter_id == self.viewer_id()

    def get_can_pin(self, obj):
        return self.viewer_is_author()

    def get_can_delete(self, obj):
        return self.viewer_is_author()

    class Meta:
        model = Thread
        fields = ['id', 'block', 'starter', 'starter_name', 'created_at', 'is_resolved',
                  'resolved_by_name', 'is_pinned', 'comments', 'can_resolve', 'can_pin', 'can_delete']
        read_only_fields = fields
