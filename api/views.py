"""
API Views for Learning Platform

ViewSets provide automatic CRUD operations:
- list() - GET /api/courses/
- create() - POST /api/courses/
- retrieve() - GET /api/courses/{id}/
- update() - PUT /api/courses/{id}/
- partial_update() - PATCH /api/courses/{id}/
- destroy() - DELETE /api/courses/{id}/
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.db import models
from datetime import datetime

from rest_framework import viewsets, status, filters
from django_filters.rest_framework import DjangoFilterBackend

from django.shortcuts import render

from .models import Course, Lesson, Block, Enrollment, Progress
from .serializers import (
    CourseSerializer,
    LessonSerializer,
    BlockSerializer,
    EnrollmentSerializer,
    ProgressSerializer
)
from .permissions import (
    IsAuthor,
    IsOwnerOrReadOnly,
    IsPublishedOrAuthor
)


# =============================================================================
# SIMPLE API VIEWS (from Step 1)
# =============================================================================

@api_view(['GET'])
def hello_view(request):
    """Simple hello endpoint"""
    return Response({'message': 'Hello World!'})


@api_view(['GET'])
def status_view(request):
    """API status with timestamp"""
    return Response({
        'status': 'ok',
        'message': 'Learning Platform API is running',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })


# =============================================================================
# COURSE VIEWSET
# =============================================================================

class CourseViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for courses.

    Permissions:
    - GET: Everyone can list/view published courses
    - POST: Only authors can create courses
    - PUT/PATCH/DELETE: Only course owner can modify

    Auto-assignment:
    - When author creates course, they're automatically set as author
    """

    queryset = Course.objects.all()
    serializer_class = CourseSerializer

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'title']

    def get_permissions(self):
        """
        Set different permissions for different actions.

        WHY?
        - Different actions need different rules
        - Flexible security model
        - Can add payment, enrollment checks later
        """
        if self.action in ['list', 'retrieve']:
            # Anyone can view published courses
            permission_classes = [AllowAny]
        elif self.action == 'create':
            # Must be authenticated author to create
            permission_classes = [IsAuthenticated, IsAuthor]
        else:
            # Must be owner to edit/delete
            permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter queryset based on user role.

        WHY?
        - Students only see published courses
        - Authors see their own courses (including unpublished)
        - Admins see everything

        Returns:
            QuerySet of courses filtered by permissions
        """
        user = self.request.user

        # For list view
        if self.action == 'list':
            if user.is_authenticated and user.role == 'AUTHOR':
                # Authors see: published courses + their own unpublished courses
                return Course.objects.filter(
                    models.Q(is_published=True) | models.Q(author=user)
                ).distinct()
            else:
                # Everyone else sees only published courses
                return Course.objects.filter(is_published=True)

        # For detail view (retrieve)
        return Course.objects.all()

    def perform_create(self, serializer):
        """
        Automatically set the author when creating a course.

        WHY?
        - Author shouldn't manually set themselves as author
        - Security: prevents user from setting someone else as author
        - Convenience: one less field to send from frontend

        BEFORE: Frontend sends: {"title": "...", "author": 123}
        AFTER: Frontend sends: {"title": "..."} ← author auto-set!
        """
        serializer.save(author=self.request.user)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated, IsAuthor])
    def my_courses(self, request):
        """
        Custom endpoint: GET /api/courses/my_courses/

        Returns all courses created by the logged-in author.

        WHY?
        - Easy "My Courses" dashboard for authors
        - No need to filter on frontend
        - Shows unpublished courses too
        """
        courses = Course.objects.filter(author=request.user)
        serializer = self.get_serializer(courses, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOwnerOrReadOnly])
    def publish(self, request, pk=None):
        """
        Custom endpoint: POST /api/courses/{id}/publish/

        Publish/unpublish a course.

        WHY?
        - Separate action from regular update
        - Can add validation (e.g., "must have 3+ lessons to publish")
        - Clear intent
        """
        course = self.get_object()
        course.is_published = not course.is_published
        course.save()

        serializer = self.get_serializer(course)
        return Response(serializer.data)


# =============================================================================
# LESSON VIEWSET
# =============================================================================

class LessonViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for lessons.

    Permissions:
    - Students can view lessons in enrolled courses
    - Authors can create/edit lessons in THEIR courses only
    """

    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated, IsAuthor, IsOwnerOrReadOnly]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter lessons based on course access.

        URL patterns:
        - /api/lessons/ → All lessons user has access to
        - /api/lessons/?course={id} → Lessons for specific course
        """
        user = self.request.user
        queryset = Lesson.objects.all()

        # Filter by course if provided
        course_id = self.request.query_params.get('course', None)
        if course_id:
            queryset = queryset.filter(course_id=course_id)

        # Authors see lessons from their courses
        if user.role == 'AUTHOR':
            queryset = queryset.filter(course__author=user)
        else:
            # Students see lessons from enrolled courses
            enrolled_courses = Enrollment.objects.filter(student=user).values_list('course_id', flat=True)
            queryset = queryset.filter(course_id__in=enrolled_courses)

        return queryset

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAuthor, IsOwnerOrReadOnly])
    def reorder(self, request, pk=None):
        """
        Reorder a lesson.

        POST /api/lessons/{id}/reorder/
        Body: {"new_order": 3}

        This will:
        1. Move lesson to new position
        2. Shift other lessons automatically
        """
        lesson = self.get_object()
        new_order = request.data.get('new_order')

        if not new_order:
            return Response(
                {'error': 'new_order is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            new_order = int(new_order)
        except ValueError:
            return Response(
                {'error': 'new_order must be a number'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if new_order < 1:
            return Response(
                {'error': 'new_order must be at least 1'},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_order = lesson.order_index
        course = lesson.course

        # Get all lessons in this course
        lessons = list(course.lessons.all().order_by('order_index'))
        max_order = len(lessons)

        if new_order > max_order:
            new_order = max_order

        # Same position, no change needed
        if old_order == new_order:
            serializer = self.get_serializer(lesson)
            return Response(serializer.data)

        # Reorder logic
        if old_order < new_order:
            # Moving down: shift lessons between old and new position up
            for l in lessons:
                if old_order < l.order_index <= new_order:
                    l.order_index -= 1
                    l.save()
        else:
            # Moving up: shift lessons between new and old position down
            for l in lessons:
                if new_order <= l.order_index < old_order:
                    l.order_index += 1
                    l.save()

        # Update current lesson
        lesson.order_index = new_order
        lesson.save()

        serializer = self.get_serializer(lesson)
        return Response(serializer.data)


# =============================================================================
# BLOCK VIEWSET
# =============================================================================

class BlockViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for blocks.

    Permissions:
    - Same as lessons (inherited from course ownership)
    """

    queryset = Block.objects.all()
    serializer_class = BlockSerializer

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated, IsAuthor, IsOwnerOrReadOnly]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter blocks based on lesson access.

        URL patterns:
        - /api/blocks/?lesson={id} → Blocks for specific lesson
        """
        user = self.request.user
        queryset = Block.objects.all()

        # Filter by lesson if provided
        lesson_id = self.request.query_params.get('lesson', None)
        if lesson_id:
            queryset = queryset.filter(lesson_id=lesson_id)

        # Authors see blocks from their courses
        if user.role == 'AUTHOR':
            queryset = queryset.filter(lesson__course__author=user)
        else:
            # Students see blocks from enrolled courses
            enrolled_courses = Enrollment.objects.filter(student=user).values_list('course_id', flat=True)
            queryset = queryset.filter(lesson__course_id__in=enrolled_courses)

        return queryset


# =============================================================================
# ENROLLMENT VIEWSET
# =============================================================================

class EnrollmentViewSet(viewsets.ModelViewSet):
    """
    Manage course enrollments.

    Endpoints:
    - GET /api/enrollments/ → My enrollments
    - POST /api/enrollments/ → Enroll in course
    - DELETE /api/enrollments/{id}/ → Unenroll
    """

    queryset = Enrollment.objects.all()
    serializer_class = EnrollmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Students see only their enrollments"""
        return Enrollment.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        """Automatically set student when enrolling"""
        serializer.save(student=self.request.user)

    @action(detail=False, methods=['post'])
    def enroll(self, request):
        """
        Enroll in a course.

        POST /api/enrollments/enroll/
        Body: {"course": "course-uuid"}
        """
        course_id = request.data.get('course')

        if not course_id:
            return Response(
                {'error': 'Course ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        course = get_object_or_404(Course, id=course_id, is_published=True)

        # Check if already enrolled
        if Enrollment.objects.filter(student=request.user, course=course).exists():
            return Response(
                {'message': 'Already enrolled in this course'},
                status=status.HTTP_200_OK
            )

        # Create enrollment
        enrollment = Enrollment.objects.create(
            student=request.user,
            course=course
        )

        serializer = self.get_serializer(enrollment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# =============================================================================
# PROGRESS VIEWSET
# =============================================================================

class ProgressViewSet(viewsets.ModelViewSet):
    """
    Track student progress.

    Endpoints:
    - GET /api/progress/ → My progress
    - POST /api/progress/ → Submit block completion
    """

    queryset = Progress.objects.all()
    serializer_class = ProgressSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Students see only their own progress"""
        user = self.request.user

        if user.role == 'AUTHOR':
            # Authors can see progress of students in their courses
            return Progress.objects.filter(lesson__course__author=user)
        else:
            # Students see only their progress
            return Progress.objects.filter(student=user)

    def perform_create(self, serializer):
        """Automatically set student when creating progress"""
        serializer.save(student=self.request.user)

    @action(detail=False, methods=['post'])
    def submit(self, request):
        """
        Submit block completion/answer.

        POST /api/progress/submit/
        Body: {
            "block": "block-uuid",
            "completed": true,
            "answer": {...},  # Optional
            "is_correct": true  # Optional
        }
        """
        block_id = request.data.get('block')

        if not block_id:
            return Response(
                {'error': 'Block ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        block = get_object_or_404(Block, id=block_id)

        # Get or create progress record
        progress, created = Progress.objects.get_or_create(
            student=request.user,
            block=block,
            lesson=block.lesson,
            defaults={
                'completed': request.data.get('completed', False),
                'answer': request.data.get('answer'),
                'is_correct': request.data.get('is_correct')
            }
        )

        # Update if already exists
        if not created:
            progress.completed = request.data.get('completed', progress.completed)
            progress.answer = request.data.get('answer', progress.answer)
            progress.is_correct = request.data.get('is_correct', progress.is_correct)

            if progress.completed:
                progress.completed_at = datetime.now()

            progress.save()

        serializer = self.get_serializer(progress)
        return Response(serializer.data)


def lesson_viewer(request):
    return render(request, 'lesson_viewer.html')