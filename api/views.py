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
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.http import Http404
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
from .block_content import grade_fill, grade_quiz, normalize_test, test_visibility
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


def get_accessible_block(user, block_id, missing_message, forbidden_message):
    """
    The block a user may work on (run code, submit answers), else a DRF error.

    Order: missing id → 400, unknown or malformed id → 404, block outside the
    user's content access (BlockQuerySet.visible_to: own ∪ enrolled) → 403.
    Errors render as {"detail": ...}.
    """
    if not block_id:
        raise ParseError(missing_message)
    try:
        block = Block.objects.select_related('lesson__course').get(pk=uuid.UUID(str(block_id)))
    except (ValueError, Block.DoesNotExist):
        raise NotFound(gettext('Блок не найден.'))
    if not Block.objects.visible_to(user).filter(pk=block.pk).exists():
        raise PermissionDenied(forbidden_message)
    return block


def record_answer(user, block, answer, is_correct):
    """
    Save a server-graded submission: Progress (attempts +1) and, for task
    blocks, an Attempt. Returns the Progress, or None when the block was
    already solved: a solved block stays solved, and re-solving it is practice
    that is graded but not recorded (as before, when such submissions got 400).
    """
    existing = Progress.objects.filter(student=user, block=block).first()
    if existing and existing.is_correct:
        return None

    progress, _ = Progress.objects.get_or_create(
        student=user,
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

    # Attempt history (TEXT blocks carry no meaningful answer).
    if block.type in ('QUIZ', 'CODE', 'FILL'):
        Attempt.objects.create(student=user, block=block, answer=answer, is_correct=is_correct)
    return progress


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
        """The CODE block to run code for; raises a DRF error otherwise."""
        block = get_accessible_block(
            request.user,
            request.data.get('block_id'),
            missing_message=gettext('Не указан block_id.'),
            forbidden_message=gettext('Запускать код могут только записанные на курс учащиеся и автор курса.'),
        )
        if block.type != 'CODE':
            raise ParseError(gettext('Код можно запускать только в блоке с задачей.'))
        return block


class RunCodeView(CodeRunnerAccessMixin, APIView):
    """Execute Python code and return stdout/stderr (body: block_id, code, stdin, version)"""

    def post(self, request):
        self.check_block_access(request)
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
    """
    Grade code against the BLOCK'S stored tests (body: block_id, code, version).

    Any `tests` sent by the browser are ignored. All stored tests run, hidden
    ones included, stopping at the first failure (as before). The server decides
    is_correct and records Progress + Attempt (see record_answer).

    Results reveal input / expected / actual output (or stderr) only for tests
    visible to students (block_content.test_visibility); hidden tests report only
    passed / not passed. Response: status (success | wrong_answer | error),
    test_number + hidden for the failing test, results, passed, total,
    is_correct, recorded.
    """

    def post(self, request):
        block = self.check_block_access(request)
        code = request.data.get('code', '')
        version = request.data.get('version', '')
        tests = block.content.get('tests') or []
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
            outcome = self.run_all(tmp_path, version, tests)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        is_correct = outcome['status'] == 'success'
        progress = record_answer(request.user, block, {'code': code}, is_correct)
        outcome['is_correct'] = is_correct
        outcome['recorded'] = progress is not None
        return Response(outcome)

    @staticmethod
    def run_all(tmp_path, version, tests):
        visible = test_visibility(tests)
        total = len(tests)
        results = []

        def stop(status_, i, **details):
            """Failing test i: details only when the test is visible."""
            body = {
                'status': status_,
                'test_number': i + 1,
                'hidden': not visible[i],
                'results': results,
                'passed': sum(1 for r in results if r['passed']),
                'total': total,
            }
            if visible[i]:
                body.update(details)
            return body

        for i, test in enumerate(tests):
            stdin, expected = normalize_test(test)
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
            except subprocess.TimeoutExpired:
                return stop('error', i, input=stdin, stderr='Time limit exceeded (5s)')

            # Code error — stop with the traceback (visible tests only)
            if proc.returncode != 0:
                return stop('error', i, input=stdin, stderr=proc.stderr)

            actual = proc.stdout.strip()
            passed = actual == expected.strip()
            result = {'test_number': i + 1, 'passed': passed, 'hidden': not visible[i]}
            if visible[i]:
                result.update(input=stdin, expected=expected.strip(), actual=actual)
            results.append(result)

            # Wrong answer — stop and show details (visible tests only)
            if not passed:
                return stop('wrong_answer', i, input=stdin,
                            expected=expected.strip(), actual=actual)

        return {'status': 'success', 'results': results, 'passed': total, 'total': total}


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
        # list and retrieve: one rule (published for everyone, unpublished only for
        # their author; see CourseQuerySet.visible_to). Others get 404 on detail.
        if self.action in ('list', 'retrieve'):
            return Course.objects.visible_to(self.request.user)

        # Write actions: unchanged. Ownership is enforced by IsOwnerOrReadOnly.
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
    - Read: the course's author and its enrolled students only
      (LessonQuerySet.visible_to). list/retrieve stay AllowAny so anonymous
      requests get an empty list / 404 rather than 401.
    - Authors can create/edit lessons in THEIR courses only
    """

    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            # AllowAny: get_queryset() restricts reads (anonymous → empty / 404)
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

        Reads (list/retrieve) follow LessonQuerySet.visible_to: own courses
        (author) ∪ enrolled courses (student); anonymous users get nothing.
        Writes keep the author's own courses (IsAuthor + IsOwnerOrReadOnly).
        """
        user = self.request.user
        if self.action in ('list', 'retrieve'):
            queryset = Lesson.objects.visible_to(user)
        else:
            queryset = Lesson.objects.filter(course__author=user)

        # Filter by course if provided
        course_id = self.request.query_params.get('course', None)
        if course_id:
            queryset = queryset.filter(course_id=course_id)

        return queryset

    def retrieve(self, request, *args, **kwargs):
        """
        A lesson outside the user's access is a 404. When the lesson belongs to
        a PUBLISHED course, the body carries course_slug so the viewer can link
        to the public course page (whose page and syllabus are public anyway).
        Lessons of unpublished courses and unknown ids get a plain 404.
        """
        try:
            return super().retrieve(request, *args, **kwargs)
        except Http404:
            course_slug = None
            try:
                course_slug = (
                    Course.objects.filter(is_published=True, lessons__pk=uuid.UUID(str(kwargs.get('pk'))))
                    .values_list('slug', flat=True).first()
                )
            except ValueError:
                pass
            body = {'detail': gettext('Урок недоступен.')}
            if course_slug:
                body['course_slug'] = course_slug
            return Response(body, status=status.HTTP_404_NOT_FOUND)

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
    - Read: the course's author and its enrolled students only
      (BlockQuerySet.visible_to); anonymous requests get an empty list / 404.
    - Authors can create/edit blocks in THEIR courses only
    """

    queryset = Block.objects.all()
    serializer_class = BlockSerializer

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            # AllowAny: get_queryset() restricts reads (anonymous → empty / 404)
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated, IsAuthor, IsOwnerOrReadOnly]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Filter blocks based on lesson access.

        URL patterns:
        - /api/blocks/?lesson={id} → Blocks for specific lesson

        Reads (list/retrieve) follow BlockQuerySet.visible_to: own courses
        (author) ∪ enrolled courses (student); anonymous users get nothing.
        Writes keep the author's own courses (IsAuthor + IsOwnerOrReadOnly).
        """
        user = self.request.user
        if self.action in ('list', 'retrieve'):
            queryset = Block.objects.visible_to(user)
        else:
            queryset = Block.objects.filter(lesson__course__author=user)
        # BlockSerializer picks the author/student view per block from the course.
        queryset = queryset.select_related('lesson__course')

        # Filter by lesson if provided
        lesson_id = self.request.query_params.get('lesson', None)
        if lesson_id:
            queryset = queryset.filter(lesson_id=lesson_id)

        return queryset


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


class ProgressSubmitView(generics.CreateAPIView):
    """
    POST /api/progress/submit/   Body: {"block": "<uuid>", "answer": {...}}
    Student submits an answer to a TEXT, QUIZ or FILL block.

    Access: anonymous → 401; missing block → 400; unknown block → 404;
    not enrolled in the block's course and not its author → 403.

    Grading is server-side only; a client-sent is_correct is ignored.
    - TEXT: marks as completed (is_correct stays None).
    - QUIZ: answer {"selected": <option index>} vs correct_answer.
    - FILL: answer {"blanks": [...]} vs the template's {{answer}} gaps.
    - CODE: 400 — code is graded only by POST /api/run-tests/.

    Response: the progress record (ProgressSerializer, incl. is_correct and
    feedback: explanation when correct, FILL gap results) plus "recorded".
    Re-solving an already solved block is graded but not recorded.
    """
    serializer_class = ProgressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        block = get_accessible_block(
            request.user,
            request.data.get('block'),
            missing_message=gettext('Не указан блок.'),
            forbidden_message=gettext('Отвечать могут только записанные на курс учащиеся и автор курса.'),
        )
        if block.type == 'CODE':
            raise ParseError(gettext('Задачи с кодом проверяются запуском тестов.'))

        answer = request.data.get('answer')
        if block.type == 'QUIZ':
            is_correct = grade_quiz(block.content, answer)
        elif block.type == 'FILL':
            is_correct = grade_fill(block.content, answer)
        else:
            is_correct = None  # TEXT: not applicable

        progress = record_answer(request.user, block, answer, is_correct)
        recorded = progress is not None
        if not recorded:
            # Already solved: report this attempt's result, keep the stored record.
            progress = Progress(student=request.user, block=block, lesson=block.lesson,
                                answer=answer, is_correct=is_correct, completed=True)

        data = dict(self.get_serializer(progress).data)
        data['recorded'] = recorded
        return Response(data, status=status.HTTP_200_OK)


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
        # select_related: ProgressSerializer.feedback reads each record's block.
        return Progress.objects.filter(
            student=self.request.user,
            lesson__course_id=course_id
        ).select_related('block', 'lesson', 'student')


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
            # Own progress, but only for courses whose content the user can read
            # (enrolled or own): this response lists the course's lessons and blocks.
            course = get_object_or_404(Course.objects.with_content_access(request.user), id=course_id)
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