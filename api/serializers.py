"""
Serializers for the Learning Platform API

Serializers convert between:
- Python objects (models) → JSON (for API responses)
- JSON (from API requests) → Python objects (for database)

"""

from rest_framework import serializers
from .models import User, Course, Lesson, Block, Enrollment, Progress


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
        read_only_fields = ['id', 'date_joined']
        extra_kwargs = {
            'password': {'write_only': True}  # Never return password in API!
        }

    def get_course_count(self, obj):
        """Count how many courses this user has authored"""
        return obj.authored_courses.count()


# =============================================================================
# COURSE SERIALIZER
# =============================================================================

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
            'lesson_count',  # Extra: number of lessons
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'author', 'created_at', 'updated_at']

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

    def get_block_count(self, obj):
        """Count blocks in this lesson"""
        return obj.blocks.count()

    def validate_title(self, value):
        """Validate lesson title."""
        if not value or not value.strip():
            raise serializers.ValidationError("Title cannot be empty.")

        if len(value.strip()) < 2:
            raise serializers.ValidationError("Title must be at least 2 characters.")

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


# =============================================================================
# BLOCK SERIALIZER
# =============================================================================

class BlockSerializer(serializers.ModelSerializer):
    """
    Serializer for Block model.

    The content field is JSONField - Django automatically handles conversion!
    We don't need to do anything special.
    """

    lesson_title = serializers.CharField(source='lesson.title', read_only=True)

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

    def validate_content(self, value):
        """
        Custom validation for content field.

        Makes sure content has required fields based on block type.
        This runs automatically when data comes in from API!
        """
        block_type = self.initial_data.get('type')

        if block_type == 'TEXT':
            if 'html' not in value:
                raise serializers.ValidationError(
                    "TEXT blocks must have 'html' field in content"
                )

        elif block_type == 'QUIZ':
            required_fields = ['question', 'options', 'correct_answer']
            for field in required_fields:
                if field not in value:
                    raise serializers.ValidationError(
                        f"QUIZ blocks must have '{field}' field in content"
                    )

        elif block_type == 'CODE':
            required_fields = ['prompt', 'starter_code']
            for field in required_fields:
                if field not in value:
                    raise serializers.ValidationError(
                        f"CODE blocks must have '{field}' field in content"
                    )

        return value


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


