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

from rest_framework import generics, permissions, viewsets, status, filters, views
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from datetime import datetime
import subprocess
import sys
import tempfile
import os
import uuid

from django_filters.rest_framework import DjangoFilterBackend

from django.shortcuts import render
from rest_framework.views import APIView

from .models import Course, Lesson, Block, Enrollment, Progress, Message, Attempt
from .serializers import (
    CourseSerializer,
    LessonSerializer,
    BlockSerializer,
    EnrollmentSerializer,
    ProgressSerializer,
    MessageSerializer

)
from .permissions import (
    IsAuthor,
    IsOwnerOrReadOnly,
    IsPublishedOrAuthor
)
from django.utils import timezone
from django.utils.translation import gettext

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


PYTHON_BINARIES = {
    'Python 3.10': '/usr/local/bin/python3.10',
    'Python 3.12': '/usr/local/bin/python3.12',
}


def resolve_python(version_str):
    # In Docker (Linux) the mapped binaries exist — return them.
    # In manual setup (Windows/macOS) they don't, so fall back to the
    # interpreter running Django, which is whatever's in the venv.
    path = PYTHON_BINARIES.get(version_str)
    if path and os.path.exists(path):
        return path
    return sys.executable


class CodeRunnerAccessMixin:
    """
    Access rules shared by /api/run-code/ and /api/run-tests/.

    - not authenticated → 401 (permission class)
    - more than 30 runs/min per user (both endpoints together) → 429
      (ScopedRateThrottle, scope 'code_run', rate in settings.REST_FRAMEWORK)
    - body must carry block_id of a CODE block:
      missing → 400, unknown → 404, user not enrolled in the block's course
      and not its author → 403, block not CODE → 400.
    Execution itself (subprocess, timeout, interpreters) is unchanged.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'code_run'

    def check_block_access(self, request):
        """None when the user may run code for this block, else an error Response."""
        block_id = request.data.get('block_id')
        if not block_id:
            return Response({'error': gettext('Не указан block_id.')}, status=400)
        try:
            block = Block.objects.select_related('lesson__course').get(pk=uuid.UUID(str(block_id)))
        except (ValueError, Block.DoesNotExist):
            return Response({'error': gettext('Блок не найден.')}, status=404)

        course = block.lesson.course
        user = request.user
        if course.author_id != user.id and not Enrollment.objects.filter(
            student=user, course=course
        ).exists():
            return Response(
                {'error': gettext('Запускать код могут только записанные на курс учащиеся и автор курса.')},
                status=403,
            )
        if block.type != 'CODE':
            return Response({'error': gettext('Код можно запускать только в блоке с задачей.')}, status=400)
        return None


class RunCodeView(CodeRunnerAccessMixin, APIView):
    """Execute Python code and return stdout/stderr (body: block_id, code, stdin, version)"""

    def post(self, request):
        denied = self.check_block_access(request)
        if denied:
            return denied
        code = request.data.get('code', '')
        stdin = request.data.get('stdin', '')
        version = request.data.get('version', '')
        if not code.strip():
            return Response({'error': 'No code provided'}, status=400)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', delete=False, encoding='utf-8'
            ) as f:
                f.write(code)
                tmp_path = f.name

            run_env = os.environ.copy()
            run_env['PYTHONUTF8'] = '1'
            result = subprocess.run(
                [resolve_python(version), tmp_path],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=5,
                encoding='utf-8',
                errors='replace',
                env=run_env,
            )
            return Response({
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
            })
        except subprocess.TimeoutExpired:
            return Response({'error': 'Time limit exceeded (5s)'}, status=408)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


class RunTestsView(CodeRunnerAccessMixin, APIView):
    """Run code against multiple test cases (body: block_id, code, tests, version)"""

    def post(self, request):
        denied = self.check_block_access(request)
        if denied:
            return denied
        code = request.data.get('code', '')
        tests = request.data.get('tests', [])
        version = request.data.get('version', '')
        if not code.strip():
            return Response({'error': 'No code provided'}, status=400)
        if not tests:
            return Response({'error': 'No tests provided'}, status=400)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', delete=False, encoding='utf-8'
            ) as f:
                f.write(code)
                tmp_path = f.name

            results = []
            for i, test in enumerate(tests):
                stdin = test.get('input', '') if isinstance(test, dict) else ''
                expected = test.get('expected', '') if isinstance(test, dict) else test
                try:
                    run_env = os.environ.copy()
                    run_env['PYTHONUTF8'] = '1'
                    proc = subprocess.run(
                        [resolve_python(version), tmp_path],
                        input=stdin,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        encoding='utf-8',
                        errors='replace',
                        env=run_env,
                    )
                    # Code error — return immediately with traceback
                    if proc.returncode != 0:
                        return Response({
                            'status': 'error',
                            'test_number': i + 1,
                            'input': stdin,
                            'stderr': proc.stderr,
                        })

                    actual = proc.stdout.strip()
                    passed = actual == expected.strip()
                    results.append({
                        'input': stdin,
                        'expected': expected.strip(),
                        'actual': actual,
                        'passed': passed,
                    })

                    # Wrong answer — stop and show details
                    if not passed:
                        return Response({
                            'status': 'wrong_answer',
                            'test_number': i + 1,
                            'input': stdin,
                            'expected': expected.strip(),
                            'actual': actual,
                            'results': results,
                            'passed': sum(1 for r in results if r['passed']),
                            'total': len(tests),
                        })

                except subprocess.TimeoutExpired:
                    return Response({
                        'status': 'error',
                        'test_number': i + 1,
                        'input': stdin,
                        'stderr': 'Time limit exceeded (5s)',
                    })

            return Response({
                'status': 'success',
                'results': results,
                'passed': len(results),
                'total': len(results),
            })
        except Exception as e:
            return Response({'error': str(e)}, status=500)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


class UploadImageView(APIView):
    """
    POST /api/upload-image/  (author only, multipart form field: 'image')

    Saves an author-uploaded lesson image to MEDIA_ROOT/lesson_images/ and
    returns its absolute URL. The rich-text editor inserts that URL as an
    <img> in the block's HTML. build_absolute_uri makes the URL work both in
    dev (React on :5173, Django on :8000) and when embedded via iframe.
    """
    permission_classes = [IsAuthenticated, IsAuthor]
    parser_classes = [MultiPartParser, FormParser]

    # content_type -> file extension
    ALLOWED_TYPES = {
        'image/png': 'png',
        'image/jpeg': 'jpg',
        'image/gif': 'gif',
        'image/webp': 'webp',
        'image/svg+xml': 'svg',
    }
    MAX_BYTES = 5 * 1024 * 1024  # 5 MB

    def post(self, request):
        upload = request.FILES.get('image')
        if not upload:
            return Response({'error': 'No image provided'}, status=status.HTTP_400_BAD_REQUEST)

        if upload.size > self.MAX_BYTES:
            return Response(
                {'error': 'Image too large (max 5 MB)'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ext = self.ALLOWED_TYPES.get(upload.content_type)
        if not ext:
            return Response(
                {'error': f'Unsupported image type: {upload.content_type}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filename = f'lesson_images/{uuid.uuid4().hex}.{ext}'
        saved_path = default_storage.save(filename, upload)
        url = request.build_absolute_uri(settings.MEDIA_URL + saved_path)
        return Response({'url': url}, status=status.HTTP_201_CREATED)


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
            if user.is_authenticated and hasattr(user, 'role') and user.role == 'AUTHOR':
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

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAuthor])
    def enroll_student(self, request, pk=None):
        """
        Teacher adds a student to their course by username.

        POST /api/courses/{id}/enroll_student/
        Body: {"username": "alice"}
        """
        from django.contrib.auth import get_user_model
        User = get_user_model()

        course = self.get_object()
        username = request.data.get('username')

        if not username:
            return Response(
                {'error': 'Username is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Find the student
        try:
            student = User.objects.get(username=username, role='STUDENT')
        except User.DoesNotExist:
            return Response(
                {'error': 'Student not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if already enrolled
        if Enrollment.objects.filter(student=student, course=course).exists():
            return Response(
                {'error': 'Student already enrolled'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Enroll the student
        enrollment = Enrollment.objects.create(
            student=student,
            course=course
        )

        return Response(
            {'message': f'{username} successfully enrolled'},
            status=status.HTTP_201_CREATED
        )

# =============================================================================
# LESSON VIEWSET
# =============================================================================

class LessonViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for lessons.

    Permissions:
    - Anyone can view lessons in published courses (for embeddable viewer)
    - Authors can create/edit lessons in THEIR courses only

    FIX: Changed from IsAuthenticated to AllowAny for list/retrieve
    so that the lesson_viewer.html works without JWT token.
    This is correct for an embeddable platform — published content
    should be publicly readable, just like on Stepik.
    """

    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            # FIX: Allow public read access for published courses
            # This makes the embeddable lesson viewer work without login
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated, IsAuthor, IsOwnerOrReadOnly]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter lessons based on course access.

        URL patterns:
        - /api/lessons/ → All lessons user has access to
        - /api/lessons/?course={id} → Lessons for specific course

        FIX: Handle anonymous users (no role attribute).
        Anonymous users see lessons from published courses only.
        """
        user = self.request.user
        queryset = Lesson.objects.all()

        # Filter by course if provided
        course_id = self.request.query_params.get('course', None)
        if course_id:
            queryset = queryset.filter(course_id=course_id)

        # FIX: Check if user is authenticated before accessing .role
        # Anonymous users (from lesson_viewer.html) have no role attribute
        if user.is_authenticated and hasattr(user, 'role') and user.role == 'AUTHOR':
            # Authors see lessons from their courses
            queryset = queryset.filter(course__author=user)
        elif user.is_authenticated:
            # Authenticated students see lessons from enrolled courses
            enrolled_courses = Enrollment.objects.filter(student=user).values_list('course_id', flat=True)
            queryset = queryset.filter(course_id__in=enrolled_courses)
        else:
            # Anonymous users see lessons from published courses only
            queryset = queryset.filter(course__is_published=True)

        return queryset

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAuthor, IsOwnerOrReadOnly])
    def reorder(self, request, pk=None):
        """
        Reorder a lesson.

        POST /api/lessons/{id}/reorder/
        Body: {"new_order": 3}
        """
        lesson = self.get_object()
        new_order = request.data.get('new_order')

        if new_order is None:
            return Response(
                {'error': 'new_order is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_order = int(new_order)

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
    - Anyone can view blocks in published courses (for embeddable viewer)
    - Authors can create/edit blocks in THEIR courses only

    FIX: Changed from IsAuthenticated to AllowAny for list/retrieve
    """

    queryset = Block.objects.all()
    serializer_class = BlockSerializer

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            # FIX: Allow public read access for published courses
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated, IsAuthor, IsOwnerOrReadOnly]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter blocks based on lesson access.

        URL patterns:
        - /api/blocks/?lesson={id} → Blocks for specific lesson

        FIX: Handle anonymous users (no role attribute).
        Anonymous users see blocks from published courses only.
        """
        user = self.request.user
        queryset = Block.objects.all()

        # Filter by lesson if provided
        lesson_id = self.request.query_params.get('lesson', None)
        if lesson_id:
            queryset = queryset.filter(lesson_id=lesson_id)

        # FIX: Check if user is authenticated before accessing .role
        if user.is_authenticated and hasattr(user, 'role') and user.role == 'AUTHOR':
            # Authors see blocks from their courses
            queryset = queryset.filter(lesson__course__author=user)
        elif user.is_authenticated:
            # Authenticated students see blocks from enrolled courses
            enrolled_courses = Enrollment.objects.filter(student=user).values_list('course_id', flat=True)
            queryset = queryset.filter(lesson__course_id__in=enrolled_courses)
        else:
            # Anonymous users see blocks from published courses only
            queryset = queryset.filter(lesson__course__is_published=True)

        return queryset


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


class EnrollmentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/enrollments/  → student sees their own enrollments
    POST /api/enrollments/  → student self-enrolls in a course
                              Body: {"course": "<course uuid>"}

    The only self-enrolment endpoint. Rules, in this order:
    - not authenticated              → 401 (permission class)
    - role is not STUDENT            → 403
    - course missing or unpublished  → 404
    - course not free (price > 0)    → 403 (no payments yet)
    - already enrolled               → 200 with the existing enrollment
    - otherwise                      → 201 with the new enrollment
    Error bodies are {"detail": ..., "course_slug": ...}; course_slug is set when
    the course is published, so the client can link back to its public page.
    Teachers enrol students manually via POST /api/courses/{id}/enroll_student/.
    """
    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Student only sees their own enrollments
        return Enrollment.objects.filter(student=self.request.user)

    def create(self, request, *args, **kwargs):
        course = self._published_course(request.data.get('course'))
        course_slug = course.slug if course else None

        if request.user.role != 'STUDENT':
            return Response(
                {'detail': gettext('Записаться на курс может только учащийся.'),
                 'course_slug': course_slug},
                status=status.HTTP_403_FORBIDDEN,
            )
        if course is None:
            return Response(
                {'detail': gettext('Курс не найден.'), 'course_slug': None},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not course.is_free:
            return Response(
                {'detail': gettext('Это платный курс: самостоятельно записаться можно только на бесплатные курсы.'),
                 'course_slug': course_slug},
                status=status.HTTP_403_FORBIDDEN,
            )

        # get_or_create handles the duplicate race (unique_together) itself,
        # so a repeated or concurrent request never ends in an IntegrityError.
        enrollment, created = Enrollment.objects.get_or_create(
            student=request.user, course=course
        )
        return Response(
            self.get_serializer(enrollment).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @staticmethod
    def _published_course(course_id):
        """The published course with this id, or None (also for a missing or malformed id)."""
        try:
            return Course.objects.get(pk=uuid.UUID(str(course_id)), is_published=True)
        except (ValueError, Course.DoesNotExist):
            return None


class EnrollmentDeleteView(generics.DestroyAPIView):
    """
    DELETE /api/enrollments/{course_id}/  → student unenrolls from a course
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        course_id = self.kwargs['course_id']
        return generics.get_object_or_404(
            Enrollment,
            student=self.request.user,
            course_id=course_id
        )


class CourseEnrollmentsView(generics.ListAPIView):
    """
    GET /api/courses/{course_id}/enrollments/
    Author sees all students enrolled in their course.
    """
    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        course_id = self.kwargs['course_id']
        # Only the course author can see this
        return Enrollment.objects.filter(
            course_id=course_id,
            course__author=self.request.user
        )


def grade_fill(content, answer):
    """
    Grade a FILL (fill-in-the-blanks) submission server-side.

    Template holds blanks as {{answer}} or {{ans1|ans2}} (alternatives via |).
    The student submits answer = {'blanks': ['...', ...]} in template order.
    Each blank is correct if its trimmed value matches one accepted answer
    (case-insensitively unless content['case_sensitive'] is true).
    """
    import re
    template = content.get('template', '') or ''
    case_sensitive = content.get('case_sensitive', False)
    blanks = re.findall(r'\{\{(.*?)\}\}', template)
    submitted = (answer or {}).get('blanks', []) or []
    if len(submitted) != len(blanks) or not blanks:
        return False
    for raw, sub in zip(blanks, submitted):
        accepted = [a.strip() for a in raw.split('|') if a.strip()]
        value = (sub or '').strip()
        if not case_sensitive:
            value = value.lower()
            accepted = [a.lower() for a in accepted]
        if value not in accepted:
            return False
    return True


class ProgressSubmitView(generics.CreateAPIView):
    """
    POST /api/progress/submit/
    Student submits a block completion or answer.

    For TEXT blocks: just marks as completed.
    For QUIZ blocks: checks answer against correct_answer in block content.
    For CODE blocks: marks as completed (code execution comes later in frontend).
    """
    serializer_class = ProgressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        block_id = request.data.get('block')
        answer = request.data.get('answer')

        # Get the block
        block = generics.get_object_or_404(Block, id=block_id)

        # Check if progress record already exists
        existing = Progress.objects.filter(
            student=request.user,
            block=block
        ).first()

        if existing and existing.is_correct:
            return Response(
                {'detail': 'This block is already solved.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Calculate is_correct based on block type
        is_correct = None
        if block.type == 'QUIZ':
            correct_answer = block.content.get('correct_answer')
            selected = answer.get('selected') if answer else None
            is_correct = (selected == correct_answer)
        elif block.type == 'TEXT':
            is_correct = None  # Not applicable
        elif block.type == 'CODE':
            # Frontend already ran /run-tests/ and knows the outcome.
            # Trust its is_correct flag (passed in the request body).
            is_correct = request.data.get('is_correct')
        elif block.type == 'FILL':
            # Graded server-side against the template's {{answer}} markers.
            is_correct = grade_fill(block.content, answer)

        # Create or fetch the record, then increment attempts on every submission.
        # update_or_create can't easily increment, so we do it manually.
        progress, _ = Progress.objects.get_or_create(
            student=request.user,
            block=block,
            defaults={'lesson': block.lesson, 'attempts': 0},
        )
        progress.lesson = block.lesson
        progress.completed = True
        progress.answer = answer
        progress.is_correct = is_correct
        progress.attempts = (progress.attempts or 0) + 1
        progress.completed_at = timezone.now()
        progress.save()

        # Record this individual submission in the attempt history (skip TEXT
        # blocks — they don't carry a meaningful answer payload).
        if block.type in ('QUIZ', 'CODE', 'FILL'):
            Attempt.objects.create(
                student=request.user,
                block=block,
                answer=answer,
                is_correct=is_correct,
            )

        serializer = self.get_serializer(progress)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProgressCourseView(generics.ListAPIView):
    """
    GET /api/progress/course/<course_id>/
    Student sees their progress for a specific course.
    Returns completion status for every block in the course.
    """
    serializer_class = ProgressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        course_id = self.kwargs['course_id']
        return Progress.objects.filter(
            student=self.request.user,
            lesson__course_id=course_id
        )


class ProgressStatsView(APIView):
    """
    GET /api/progress/stats/
    Student sees overall statistics across all their enrolled courses.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        student = request.user

        # Get all enrolled courses
        enrollments = Enrollment.objects.filter(
            student=student
        ).select_related('course')

        stats = []
        for enrollment in enrollments:
            course = enrollment.course

            # Count total blocks in course
            total_blocks = Block.objects.filter(
                lesson__course=course
            ).count()

            # Count completed blocks
            completed_blocks = Progress.objects.filter(
                student=student,
                lesson__course=course,
                completed=True
            ).count()

            # Count correct quiz answers
            correct_answers = Progress.objects.filter(
                student=student,
                lesson__course=course,
                block__type='QUIZ',
                is_correct=True
            ).count()

            total_quizzes = Block.objects.filter(
                lesson__course=course,
                type='QUIZ'
            ).count()

            # Calculate percentage
            percentage = round(
                (completed_blocks / total_blocks * 100) if total_blocks > 0 else 0
            )

            stats.append({
                'course_id': course.id,
                'course_title': course.title,
                'total_blocks': total_blocks,
                'completed_blocks': completed_blocks,
                'progress_percentage': percentage,
                'total_quizzes': total_quizzes,
                'correct_answers': correct_answers,
            })

        return Response(stats)

class StudentProgressView(APIView):
    """
    GET /api/progress/student/<student_id>/course/<course_id>/
    Teacher sees a specific student's progress in their course.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, student_id, course_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Authors see any student's progress in their courses;
        # students see only their own.
        is_self = str(request.user.id) == str(student_id)
        is_author = request.user.role == 'AUTHOR'

        if is_self:
            course = get_object_or_404(Course, id=course_id)
        elif is_author:
            course = get_object_or_404(Course, id=course_id, author=request.user)
        else:
            return Response(
                {'error': 'Not authorized'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get the student
        student = get_object_or_404(User, id=student_id)

        # Get all blocks in the course
        blocks = Block.objects.filter(
            lesson__course=course
        ).select_related('lesson').order_by('lesson__order_index', 'order_index')

        # Get student's progress records
        progress_records = Progress.objects.filter(
            student=student,
            lesson__course=course
        )

        # Map block_id → progress
        progress_map = {str(p.block_id): p for p in progress_records}

        # Map block_id → list of attempts (oldest first)
        attempts_qs = Attempt.objects.filter(
            student=student,
            block__lesson__course=course,
        ).order_by('created_at')
        attempts_map = {}
        for a in attempts_qs:
            attempts_map.setdefault(str(a.block_id), []).append({
                'id': str(a.id),
                'answer': a.answer,
                'is_correct': a.is_correct,
                'created_at': a.created_at,
            })

        # Build response
        lessons_data = {}
        for block in blocks:
            lesson_id = str(block.lesson_id)
            if lesson_id not in lessons_data:
                lessons_data[lesson_id] = {
                    'lesson_title': block.lesson.title,
                    'lesson_order': block.lesson.order_index,
                    'blocks': []
                }

            progress = progress_map.get(str(block.id))
            lessons_data[lesson_id]['blocks'].append({
                'block_id': str(block.id),
                'block_type': block.type,
                'block_order': block.order_index,
                'completed': progress.completed if progress else False,
                'is_correct': progress.is_correct if progress else None,
                'attempts': progress.attempts if progress else 0,
                'completed_at': progress.completed_at if progress else None,
                'attempts_history': attempts_map.get(str(block.id), []),
            })

        # Count totals
        total_blocks = blocks.count()
        completed_blocks = sum(1 for p in progress_map.values() if p.completed)
        correct_answers = sum(
            1 for p in progress_map.values()
            if p.is_correct is True
        )
        total_quizzes = blocks.filter(type='QUIZ').count()

        return Response({
            'student_username': student.username,
            'course_title': course.title,
            'total_blocks': total_blocks,
            'completed_blocks': completed_blocks,
            'total_quizzes': total_quizzes,
            'correct_answers': correct_answers,
            'progress_percentage': round(
                completed_blocks / total_blocks * 100
            ) if total_blocks > 0 else 0,
            'lessons': list(lessons_data.values()),
        })

class MessageView(APIView):
    """
    GET  /api/messages/?course=<id>  ← get all messages in a course
    POST /api/messages/              ← send a message
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        course_id = request.query_params.get('course')
        if not course_id:
            return Response(
                {'error': 'course parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get all messages in this course where user is sender or receiver
        messages = Message.objects.filter(
            course_id=course_id
        ).filter(
            models.Q(sender=request.user) | models.Q(receiver=request.user)
        ).order_by('created_at')

        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)

    def post(self, request):
        course_id = request.data.get('course')
        receiver_id = request.data.get('receiver')
        text = request.data.get('text')

        if not all([course_id, receiver_id, text]):
            return Response(
                {'error': 'course, receiver and text are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        course = get_object_or_404(Course, id=course_id)

        from django.contrib.auth import get_user_model
        User = get_user_model()
        receiver = get_object_or_404(User, id=receiver_id)

        message = Message.objects.create(
            sender=request.user,
            receiver=receiver,
            course=course,
            text=text,
        )

        serializer = MessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_201_CREATED)