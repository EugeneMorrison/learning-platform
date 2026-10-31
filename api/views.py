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
from django.db import models, transaction
from django.db.models.functions import Coalesce
from collections import Counter
from datetime import datetime
import subprocess
import copy
import uuid

from django_filters.rest_framework import DjangoFilterBackend

from django.shortcuts import render
from rest_framework.views import APIView

from .models import (Course, Lesson, Block, Enrollment, Progress, Message, Attempt, Thread, Comment,
                     CommentReport, DiscussionBan)
from .chat import MAX_MESSAGE_LENGTH, chat_allowed, message_preview, notify_user, push_message
from .questions import MAX_DRAFT_LENGTH, build_context
from .discussions import (can_see_all, check_not_banned, check_post_interval, clean_text, discussion_block,
                          is_banned, is_course_author, open_reports)
from .runner import RunnerBusy, RunnerUnavailable, run_python
from .output_comparison import outputs_match
from .quiz_state import submit_quiz
from .block_content import TASK_TYPES, grade_fill, normalize_test, test_visibility
from .serializers import (
    CourseSerializer,
    LessonSerializer,
    LessonViewerSerializer,
    course_lesson_ids_in_order,
    BlockSerializer,
    EnrollmentSerializer,
    ProgressSerializer,
    MessageSerializer,
    ThreadSerializer,
    CommentSerializer,
    display_name,
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


def count_subquery(queryset, group_by):
    """COUNT(*) of a correlated subquery (grouped on a field it's already filtered to one value of), 0 if empty."""
    counted = queryset.order_by().values(group_by).annotate(n=models.Count('pk')).values('n')[:1]
    return Coalesce(models.Subquery(counted), 0)


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

    @staticmethod
    def hidden_code(block):
        """The block's stored header / footer as run_python() keywords. Never
        taken from the request: students must not see or replace them."""
        content = block.content or {}
        return {'header': content.get('header') or '', 'footer': content.get('footer') or ''}


class RunCodeView(CodeRunnerAccessMixin, APIView):
    """
    Execute Python code and return stdout/stderr (body: block_id, code, stdin,
    version). Runs the block's stored hidden header / footer around the code.
    """

    def post(self, request):
        block = self.check_block_access(request)
        code = request.data.get('code', '')
        stdin = request.data.get('stdin', '')
        version = request.data.get('version', '')
        if not code.strip():
            return Response({'error': 'No code provided'}, status=400)

        # api/runner.py: the code runs in the runner container, not here.
        try:
            result = run_python(code, stdin=stdin, version=version, **self.hidden_code(block))
            return Response({
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
            })
        except subprocess.TimeoutExpired:
            return Response({'error': 'Time limit exceeded (5s)'}, status=408)
        except RunnerBusy:
            return Response({'error': 'Code runner is busy, try again'}, status=503)
        except RunnerUnavailable:
            return Response({'error': 'Code runner is not available'}, status=503)
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class RunTestsView(CodeRunnerAccessMixin, APIView):
    """
    Grade code against the BLOCK'S stored tests (body: block_id, code, version).

    Any `tests` sent by the browser are ignored. All stored tests run, hidden
    ones included, stopping at the first failure (as before). Each run is the
    block's hidden header + code + footer; the footer's output is part of the
    compared stdout. The server decides is_correct and records Progress +
    Attempt (see record_answer) with the student's code only.

    Comparison uses the block's stored output_comparison (missing = exact),
    for every test. The request cannot override it; the runner never sees it.

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

        try:
            outcome = self.run_all(code, version, tests,
                                   output_comparison=block.content.get('output_comparison', 'exact'),
                                   **self.hidden_code(block))
        except RunnerBusy:
            return Response({'error': 'Code runner is busy, try again'}, status=503)
        except RunnerUnavailable:
            return Response({'error': 'Code runner is not available'}, status=503)
        except Exception as e:
            return Response({'error': str(e)}, status=500)

        is_correct = outcome['status'] == 'success'
        progress = record_answer(request.user, block, {'code': code}, is_correct)
        outcome['is_correct'] = is_correct
        outcome['recorded'] = progress is not None
        return Response(outcome)

    @staticmethod
    def run_all(code, version, tests, header='', footer='', output_comparison='exact'):
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
                # A fresh run per test (api/runner.py): nothing carries over,
                # and the expected output never leaves this process.
                proc = run_python(code, stdin=stdin, version=version,
                                  header=header, footer=footer)
            except subprocess.TimeoutExpired:
                return stop('error', i, input=stdin, stderr='Time limit exceeded (5s)')

            # Code error — stop with the traceback (visible tests only)
            if proc.returncode != 0:
                return stop('error', i, input=stdin, stderr=proc.stderr)

            actual = proc.stdout.strip()
            passed = outputs_match(expected, actual, output_comparison)
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

        Each course also carries progress (dashboard cards), by the course
        page's rule (QUIZ/CODE/FILL tasks, solved = is_correct): task_count,
        solved_count (the author's own), student_count (enrolled) and
        students_solved (their correct tasks, summed). Subqueries, one query.
        """
        course = models.OuterRef('pk')
        tasks = Block.objects.filter(lesson__course=course, type__in=TASK_TYPES)
        solved = Progress.objects.filter(is_correct=True, block__lesson__course=course, block__type__in=TASK_TYPES)
        courses = list(Course.objects.filter(author=request.user).annotate(
            task_count=count_subquery(tasks, 'lesson__course'),
            solved_count=count_subquery(solved.filter(student=request.user), 'student'),
            student_count=count_subquery(
                Enrollment.objects.filter(course=course).exclude(student=request.user), 'course'),
            students_solved=count_subquery(
                solved.filter(student__enrollments__course=course).exclude(student=request.user),
                'block__lesson__course'),
        ))
        serializer = self.get_serializer(courses, many=True)
        stats = ('task_count', 'solved_count', 'student_count', 'students_solved')
        return Response([
            {**row, **{name: getattr(c, name) for name in stats}}
            for row, c in zip(serializer.data, courses)
        ])

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


class ParentOwnerMixin:
    """
    Create/update of a child object: its PARENT must belong to the requesting
    author too (a lesson's course, a block's lesson), not only the object
    itself. Without this an author could create lessons/blocks in another
    author's course, or move their own into it by changing course/lesson.

    The rule is IsOwnerOrReadOnly applied to the parent, via
    check_object_permissions: not the owner → 403, like a write to another
    author's course. An unknown parent id is already a 400 from the
    serializer's related field.
    """
    parent_field = None

    def check_parent_owner(self, serializer):
        parent = serializer.validated_data.get(self.parent_field)
        if parent is not None:
            self.check_object_permissions(self.request, parent)

    def perform_create(self, serializer):
        self.check_parent_owner(serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self.check_parent_owner(serializer)
        super().perform_update(serializer)


# =============================================================================
# LESSON VIEWSET
# =============================================================================

class LessonViewSet(ParentOwnerMixin, viewsets.ModelViewSet):
    """
    CRUD operations for lessons.

    Permissions:
    - Read: the course's author and its enrolled students only
      (LessonQuerySet.visible_to). list/retrieve stay AllowAny so anonymous
      requests get an empty list / 404 rather than 401.
    - Authors can create/edit lessons in THEIR courses only: another author's
      lesson is a 404 (get_queryset); a course they don't own, as the lesson's
      course on create or update, is a 403 (ParentOwnerMixin).
    """

    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    parent_field = 'course'

    def get_serializer_class(self):
        # The single-lesson read adds next_lesson_id for the viewer's navigation.
        if self.action == 'retrieve':
            return LessonViewerSerializer
        return LessonSerializer

    def get_permissions(self):
        """Set permissions based on action"""
        if self.action in ['list', 'retrieve']:
            # AllowAny: get_queryset() restricts reads (anonymous → empty / 404)
            permission_classes = [AllowAny]
        elif self.action == 'outline':
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

    @action(detail=False, methods=['get'])
    def outline(self, request):
        """
        GET /api/lessons/outline/?course=<id>  (lesson viewer's lessons panel)

        Every lesson of the course in order, with the REQUESTING user's progress:
        [{id, title, position, task_count, solved_count, passed_students,
        students_solved}]. Same rule as the viewer's "Решено X из Y задач":
        tasks are QUIZ/CODE/FILL blocks, solved means is_correct. The course
        author's solved_count is their own (trying out their tasks), and they also
        get the enrolled students': passed_students (solved every task of the
        lesson) and students_solved (their correct tasks, summed); null for
        anyone else. Only the course author and enrolled students get it
        (others: 404). One query for the counts, one more for the author's
        student stats, whatever the number of lessons.
        """
        try:
            course_id = uuid.UUID(str(request.query_params.get('course', '')))
        except ValueError:
            raise ParseError(gettext('Укажите курс: ?course=<id>.'))
        course = get_object_or_404(Course.objects.with_content_access(request.user), pk=course_id)
        is_author = course.author_id == request.user.id

        tasks = models.Q(blocks__type__in=TASK_TYPES)
        lessons = Lesson.objects.filter(course=course).annotate(
            task_count=models.Count('blocks', filter=tasks, distinct=True),
            # One Progress row per student per block, so no double counting.
            solved_count=models.Count('blocks__progress', distinct=True, filter=tasks & models.Q(
                blocks__progress__student=request.user, blocks__progress__is_correct=True)),
        ).in_bulk()

        passed_students = students_solved = None
        if is_author:
            passed_students, students_solved = Counter(), Counter()
            per_student = (
                Progress.objects.filter(
                    block__lesson__course=course, block__type__in=TASK_TYPES, is_correct=True,
                    student__enrollments__course=course,
                ).exclude(student=request.user)
                .values('block__lesson', 'student').annotate(n=models.Count('pk', distinct=True))
            )
            for row in per_student:
                lesson = lessons.get(row['block__lesson'])
                if lesson is None:
                    continue
                students_solved[lesson.pk] += row['n']
                if row['n'] == lesson.task_count:
                    passed_students[lesson.pk] += 1

        return Response([
            {
                'id': lesson_id,
                'title': lessons[lesson_id].title,
                'position': position,
                'task_count': lessons[lesson_id].task_count,
                'solved_count': lessons[lesson_id].solved_count,
                'passed_students': None if passed_students is None else passed_students[lesson_id],
                'students_solved': None if students_solved is None else students_solved[lesson_id],
            }
            # Positions from the same helper as the viewer's lesson_position.
            for position, lesson_id in enumerate(course_lesson_ids_in_order(course.id), start=1)
            if lesson_id in lessons
        ])

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAuthor, IsOwnerOrReadOnly])
    def reorder(self, request, pk=None):
        """
        Move a lesson to another place in its course (course page ↑ / ↓).

        POST /api/lessons/{id}/reorder/   Body: {"new_order": N}

        N is the 1-based POSITION in the course's ordered lessons
        (course_lesson_ids_in_order), so gaps in order_index don't matter.
        Missing or not an integer → 400; below 1 → 400; above the number of
        lessons → the last place (clamped). Owner only, as for edit/delete:
        another author's lesson is a 404, a student 403.

        The course keeps the same set of order_index values, reassigned in the
        new order, in one transaction. Lessons that change move to temporary
        values above all others first, so unique (course, order_index) never
        clashes. Returns the course's lessons in the new order.
        """
        lesson = self.get_object()
        new_order = self._parse_position(request.data.get('new_order'))
        if new_order is None:
            return Response({'error': 'new_order must be an integer'}, status=status.HTTP_400_BAD_REQUEST)
        if new_order < 1:
            return Response({'error': 'new_order must be at least 1'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            lessons = {
                l.pk: l for l in Lesson.objects.select_for_update().filter(course_id=lesson.course_id)
            }
            ids = course_lesson_ids_in_order(lesson.course_id)
            new_order = min(new_order, len(ids))
            slots = [lessons[pk].order_index for pk in ids]  # the values in use, ascending
            ids.remove(lesson.pk)
            ids.insert(new_order - 1, lesson.pk)

            changed = [(pk, slot) for pk, slot in zip(ids, slots) if lessons[pk].order_index != slot]
            temporary = max(slots) + 1
            for offset, (pk, _) in enumerate(changed):
                Lesson.objects.filter(pk=pk).update(order_index=temporary + offset)
            for pk, slot in changed:
                Lesson.objects.filter(pk=pk).update(order_index=slot)

        ordered = Lesson.objects.filter(course_id=lesson.course_id).order_by('order_index')
        return Response(self.get_serializer(ordered, many=True).data)

    @staticmethod
    def _parse_position(value):
        """An int from JSON or a form/str ("3"); None for anything else."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None


# =============================================================================
# BLOCK VIEWSET
# =============================================================================

class BlockViewSet(ParentOwnerMixin, viewsets.ModelViewSet):
    """
    CRUD operations for blocks.

    Permissions:
    - Read: the course's author and its enrolled students only
      (BlockQuerySet.visible_to); anonymous requests get an empty list / 404.
    - Authors can create/edit blocks in THEIR courses only: another author's
      block is a 404 (get_queryset); a lesson they don't own, as the block's
      lesson on create or update, is a 403 (ParentOwnerMixin).

    Create takes an optional `insert_before: <block id>` (see create()).
    Changing a block's type deletes its Progress and Attempts (perform_update).
    """

    queryset = Block.objects.all()
    serializer_class = BlockSerializer
    parent_field = 'lesson'

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

    def create(self, request, *args, **kwargs):
        """
        POST /api/blocks/ — at the end of the lesson (the client's order_index),
        or, with `insert_before: <block id>`, in that block's place: it and
        every block below move down by one (the editor's «+ Вставить блок»).
        A block id, not a position, so the block lands where the author saw
        it even if the list changed meanwhile.

        One transaction, as in duplicate(): validation and the lesson-owner
        check run first (with a free temporary order_index), so nothing moves
        unless the block can be created; any failure rolls everything back.
        An insert_before block of another lesson (or unknown) → 400.
        """
        anchor_id = request.data.get('insert_before')
        if not anchor_id:
            return super().create(request, *args, **kwargs)

        with transaction.atomic():
            try:
                anchor = Block.objects.get(pk=uuid.UUID(str(anchor_id)))
            except (ValueError, Block.DoesNotExist):
                anchor = None
            if anchor is None or str(anchor.lesson_id) != str(request.data.get('lesson')):
                raise ParseError('insert_before must be a block of the same lesson.')
            siblings = list(
                Block.objects.select_for_update()
                .filter(lesson_id=anchor.lesson_id)
                .order_by('order_index')
            )
            data = {key: request.data.get(key) for key in ('lesson', 'type', 'content')}
            data['order_index'] = siblings[-1].order_index + 1  # free until the shift
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.check_parent_owner(serializer)
            position = next(i for i, b in enumerate(siblings) if b.pk == anchor.pk)
            shift_down(siblings[position:])
            serializer.save(order_index=anchor.order_index)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        """A new type is a different task: the answers to the old one go
        (everyone's, the author's own test answers included), in the same
        transaction as the save. Also for a PATCH of `type` alone."""
        old_type = serializer.instance.type
        with transaction.atomic():
            super().perform_update(serializer)
            block = serializer.instance
            if block.type != old_type:
                Progress.objects.filter(block=block).delete()
                Attempt.objects.filter(block=block).delete()

    @action(detail=True, methods=['get'])
    def answered(self, request, pk=None):
        """
        GET /api/blocks/{id}/answered/ → {"students": N}: how many students
        have answered this block (Progress or Attempt), so the editor can warn
        before a type change resets them. The course's author is not counted
        (record_answer() also records her own test answers).

        Only the block's author: anyone else gets 404 (GET passes IsAuthor;
        get_queryset() has only the author's own blocks for this action).
        """
        block = self.get_object()
        author_id = block.lesson.course.author_id
        students = set(Progress.objects.filter(block=block)
                       .exclude(student_id=author_id).values_list('student_id', flat=True))
        students |= set(Attempt.objects.filter(block=block)
                        .exclude(student_id=author_id).values_list('student_id', flat=True))
        return Response({'students': len(students)})

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """
        POST /api/blocks/{id}/duplicate/  (lesson editor's "Копировать")

        Copies the block directly below itself: new id, same type, a deep copy
        of content (image URLs stay as they are; no files are copied). No
        progress or attempts are copied. Returns the new block (201), in the
        same shape as GET /api/blocks/{id}/.

        Permissions as for edit/delete: IsAuthenticated + IsAuthor (students
        403) + IsOwnerOrReadOnly. get_object() runs check_object_permissions,
        and get_queryset() only has the author's own blocks for write actions,
        so another author's block is a 404 (as for PATCH/DELETE).
        """
        original = self.get_object()
        with transaction.atomic():
            # Work from the position in the lesson's ordered blocks, so gaps
            # in order_index don't matter.
            siblings = list(
                Block.objects.select_for_update()
                .filter(lesson_id=original.lesson_id)
                .order_by('order_index')
            )
            position = next(i for i, b in enumerate(siblings) if b.pk == original.pk)
            shift_down(siblings[position + 1:])
            # Same validation as a block created in the editor; a failure here
            # rolls the shift back.
            serializer = self.get_serializer(data={
                'lesson': original.lesson_id,
                'type': original.type,
                'order_index': siblings[position].order_index + 1,
                'content': copy.deepcopy(original.content),
            })
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def shift_down(blocks):
    """Move `blocks` (one lesson's, in order, locked) down by one. Bottom
    first: each block steps into a free order_index, so the unique
    (lesson, order_index) never clashes."""
    for block in reversed(blocks):
        Block.objects.filter(pk=block.pk).update(order_index=block.order_index + 1)


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
        # select_related: course_title / course_cover / student_name per row, one query.
        # task_count / solved_count (dashboard progress): the course page's rule,
        # QUIZ/CODE/FILL tasks, solved = is_correct. Subqueries, so still one query.
        tasks = Block.objects.filter(lesson__course=models.OuterRef('course'), type__in=TASK_TYPES)
        solved = Progress.objects.filter(
            student=models.OuterRef('student'), is_correct=True,
            block__lesson__course=models.OuterRef('course'), block__type__in=TASK_TYPES,
        )
        return Enrollment.objects.filter(student=self.request.user).select_related('course', 'student').annotate(
            task_count=count_subquery(tasks, 'lesson__course'),
            solved_count=count_subquery(solved, 'student'),
        )

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
        ).select_related('course', 'student')


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
            progress, recorded = submit_quiz(request.user, block, answer)
            data = dict(self.get_serializer(progress).data)
            data['recorded'] = recorded
            return Response(data, status=status.HTTP_200_OK)
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
        ).select_related('block')  # the totals below read each record's block type

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
        # "Тестов верно": correct QUIZ answers out of the course's QUIZ blocks.
        # Both sides count quizzes only (solved CODE/FILL tasks are in
        # "completed_blocks"), the same as ProgressStatsView.
        correct_answers = sum(
            1 for p in progress_map.values()
            if p.is_correct is True and p.block.type == 'QUIZ'
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

        # Get all messages in this course where user is sender or receiver.
        # The id keeps the order of messages saved in the same instant.
        messages = Message.objects.filter(
            course_id=course_id
        ).filter(
            models.Q(sender=request.user) | models.Q(receiver=request.user)
        ).order_by('created_at', 'id')

        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)

    def post(self, request):
        course_id = request.data.get('course')
        receiver_id = request.data.get('receiver')
        text = request.data.get('text')
        text = text.strip() if isinstance(text, str) else ''

        if not all([course_id, receiver_id, text]):
            return Response(
                {'error': 'course, receiver and text are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Same rule as the chat WebSocket (api/chat.py): author ↔ enrolled
        # student of this course only. Also refuses malformed course ids.
        if not chat_allowed(course_id, request.user.id, receiver_id):
            raise PermissionDenied(gettext('Писать в чат курса могут только его автор и записанные на курс учащиеся.'))

        if len(text) > MAX_MESSAGE_LENGTH:
            raise ParseError(
                gettext('Сообщение слишком длинное: не больше %(max)d символов.') % {'max': MAX_MESSAGE_LENGTH}
            )

        message = Message.objects.create(
            sender=request.user,
            receiver_id=int(receiver_id),
            course_id=course_id,
            text=text,
        )

        # Also to the open chat sockets of both users, as if sent over the socket.
        return Response(push_message(message), status=status.HTTP_201_CREATED)


def _question_block(request):
    """The task block of a «Задать вопрос» request and the CODE editor draft.

    400: block_id missing or not a UUID, not a task block, draft not a string or
    longer than MAX_DRAFT_LENGTH. 404: no such block. 403: the user is not
    enrolled in the block's course (the course author included: questions go
    to the author).
    """
    try:
        block_id = uuid.UUID(str(request.data.get('block_id')))
    except ValueError:
        raise ParseError(gettext('Укажите задание: block_id.'))
    block = Block.objects.select_related('lesson__course').filter(pk=block_id).first()
    if block is None:
        raise NotFound(gettext('Задание не найдено.'))
    if block.type not in TASK_TYPES:
        raise ParseError(gettext('Вопрос можно задать только по заданию.'))
    if not Enrollment.objects.filter(course=block.lesson.course, student=request.user).exists():
        raise PermissionDenied(gettext('Задать вопрос могут только записанные на курс учащиеся.'))

    draft = request.data.get('draft')
    if draft is not None:
        if not isinstance(draft, str):
            raise ParseError(gettext('draft должен быть строкой.'))
        if len(draft) > MAX_DRAFT_LENGTH:
            raise ParseError(
                gettext('Код в редакторе слишком длинный: не больше %(max)d символов.') % {'max': MAX_DRAFT_LENGTH}
            )
    return block, draft


class QuestionPreviewView(APIView):
    """
    POST /api/questions/preview/  Body: {"block_id": "<uuid>", "draft": "<code>"?}

    What «Задать вопрос» would attach (api/questions.py build_context), for
    the student's preview. Nothing is saved. Errors as POST /api/questions/.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        block, draft = _question_block(request)
        return Response(build_context(block, request.user, draft))


class QuestionView(APIView):
    """
    POST /api/questions/  Body: {"block_id": "<uuid>", "text": "...", "draft": "<code>"?}

    «Задать вопрос»: an enrolled student asks the course author about one task.
    The message goes into their private chat (author ↔ this student only) with
    `block` and a server-built `context` snapshot (api/questions.py: the task as
    the student sees it, their latest submission, for CODE the editor draft),
    and is pushed live to both sides' open chat sockets.

    201: the message (MessageSerializer). 400: empty / too long text, bad
    block_id or draft. 403: not enrolled. 404: no such block.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        block, draft = _question_block(request)
        text = request.data.get('text')
        text = text.strip() if isinstance(text, str) else ''
        if not text:
            raise ParseError(gettext('Напишите вопрос.'))
        if len(text) > MAX_MESSAGE_LENGTH:
            raise ParseError(
                gettext('Сообщение слишком длинное: не больше %(max)d символов.') % {'max': MAX_MESSAGE_LENGTH}
            )

        course = block.lesson.course
        message = Message.objects.create(
            sender=request.user,
            receiver_id=course.author_id,
            course=course,
            text=text,
            block=block,
            context=build_context(block, request.user, draft),
        )
        return Response(push_message(message), status=status.HTTP_201_CREATED)

class UnreadMessagesView(APIView):
    """
    GET /api/messages/unread/  ← my unread messages (receiver = me)

    {"total": N, "conversations": [{course_id, course_title, other_user_id,
    other_user_name (full name, else username), other_is_author (the other
    user is the course's author: I'm the student), unread_count, has_question
    (an unread «Задать вопрос» among them), last_message: {id, preview,
    created_at, is_question}}]}, newest conversation first.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Oldest first, so each conversation ends on its latest message (the id
        # breaks ties between messages saved in the same instant).
        unread = (Message.objects.filter(receiver=request.user, is_read=False)
                  .select_related('sender', 'course').order_by('created_at', 'id'))
        groups = {}
        for message in unread:
            key = (message.course_id, message.sender_id)
            group = groups.get(key)
            if group is None:
                sender = message.sender
                group = groups[key] = {
                    'course_id': str(message.course_id),
                    'course_title': message.course.title,
                    'other_user_id': sender.id,
                    'other_user_name': sender.get_full_name() or sender.username,
                    'other_is_author': message.course.author_id == sender.id,
                    'unread_count': 0,
                    'has_question': False,
                }
            is_question = message.context is not None
            group['unread_count'] += 1
            group['has_question'] = group['has_question'] or is_question
            group['last_message'] = {
                'id': message.id,
                'preview': message_preview(message.text),
                'created_at': message.created_at,
                'is_question': is_question,
            }
        # Newest first; the id breaks ties between messages saved in the same instant.
        conversations = sorted(groups.values(), reverse=True,
                               key=lambda g: (g['last_message']['created_at'], g['last_message']['id']))
        return Response({
            'total': sum(g['unread_count'] for g in conversations),
            'conversations': conversations,
        })


class MarkReadView(APIView):
    """
    POST /api/messages/read/  Body: {"course_id": "<uuid>", "other_user_id": <id>}

    Marks read every message that user sent ME in that course: only my own
    received messages, nothing else. {"marked": N}; my other tabs get a
    {"type": "read"} notification. 400: missing / malformed ids.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            course_id = uuid.UUID(str(request.data.get('course_id')))
            other_user_id = int(request.data.get('other_user_id'))
        except (TypeError, ValueError):
            raise ParseError(gettext('Укажите course_id и other_user_id.'))
        marked = Message.objects.filter(
            receiver=request.user, sender_id=other_user_id, course_id=course_id, is_read=False,
        ).update(is_read=True)
        if marked:
            notify_user(request.user.id, {
                'type': 'read', 'course_id': str(course_id), 'other_user_id': other_user_id,
            })
        return Response({'marked': marked})


# =============================================================================
# DISCUSSIONS (public threads per task block; rules in api/discussions.py)
# =============================================================================

def discussion_threads():
    """Threads with what ThreadSerializer reads, comments in order."""
    return Thread.objects.select_related('starter', 'resolved_by', 'block__lesson__course').prefetch_related(
        models.Prefetch('comments', queryset=Comment.objects.select_related('user')))


def visible_thread(request, thread_id):
    """A thread the user may read (Thread.objects.visible_to), else 404."""
    thread = discussion_threads().visible_to(request.user).filter(pk=thread_id).first()
    if thread is None:
        raise NotFound(gettext('Обсуждение не найдено.'))
    return thread


def discussion_context(request, block, comment_ids=()):
    """Serializer context of the discussion serializers: the viewer and, for
    the comments being sent (`comment_ids`), what their moderation flags
    need. The course author gets open report counts and her banned users;
    anyone else, which of these comments they have reported."""
    author_id = block.lesson.course.author_id
    context = {'request': request, 'course_author_id': author_id}
    if request.user.id == author_id:
        context['report_counts'] = dict(
            open_reports().filter(comment_id__in=comment_ids).order_by()
            .values('comment').annotate(n=models.Count('id')).values_list('comment', 'n'))
        context['banned_ids'] = set(
            DiscussionBan.objects.filter(author_id=author_id).values_list('user_id', flat=True))
    else:
        context['reported_ids'] = set(
            CommentReport.objects.filter(reporter=request.user, comment_id__in=comment_ids)
            .values_list('comment_id', flat=True))
    return context


def thread_comment_ids(*threads):
    return [c.id for thread in threads for c in thread.comments.all()]


class BlockThreadsView(APIView):
    """
    GET  /api/blocks/<block_id>/threads/   the block's threads the user may read
    POST /api/blocks/<block_id>/threads/   Body: {"text": "..."}: start one

    GET: {"threads": [ThreadSerializer, ...] (pinned first, then open, then
    resolved; newest first), "can_see_all": the user sees every thread (the
    course author, or solved the block), "hidden_count": threads not shown
    until the block is solved, "can_post": false when the course author has
    banned the user}.
    POST 201: the new thread. 400: empty / too long text, a TEXT block.
    403: banned by the course author. 404: no such block, or the user is
    neither the course's author nor an enrolled student. 429: posted less
    than a minute ago (not the course author).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, block_id):
        block = discussion_block(request.user, block_id)
        threads = list(discussion_threads().visible_to(request.user).filter(block=block))
        sees_all = can_see_all(request.user, block)
        hidden = 0 if sees_all else Thread.objects.filter(block=block).count() - len(threads)
        context = discussion_context(request, block, thread_comment_ids(*threads))
        return Response({
            'threads': ThreadSerializer(threads, many=True, context=context).data,
            'can_see_all': sees_all,
            'hidden_count': hidden,
            'can_post': not is_banned(request.user, block),
        })

    def post(self, request, block_id):
        block = discussion_block(request.user, block_id)
        text = clean_text(request.data.get('text'))
        check_not_banned(request.user, block)
        check_post_interval(request.user, block)
        with transaction.atomic():
            thread = Thread.objects.create(block=block, starter=request.user)
            Comment.objects.create(thread=thread, user=request.user, text=text)
        thread = discussion_threads().get(pk=thread.pk)
        context = discussion_context(request, block, thread_comment_ids(thread))
        return Response(ThreadSerializer(thread, context=context).data, status=status.HTTP_201_CREATED)


class ThreadDetailView(APIView):
    """
    PATCH  /api/threads/<id>/   Body: {"is_resolved": bool} and/or {"is_pinned": bool}
    DELETE /api/threads/<id>/   the thread and all its comments

    Resolve / reopen: the thread's starter or the course author. Pin and
    delete: the course author only. 200: the thread; 204 on delete.
    400: neither field, or not a boolean. 403: not allowed. 404: a thread the
    user can't read.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, thread_id):
        thread = visible_thread(request, thread_id)
        author = is_course_author(request.user, thread.block)
        changes = {}
        for field in ('is_resolved', 'is_pinned'):
            if field in request.data:
                if not isinstance(request.data[field], bool):
                    raise ParseError(gettext('%(field)s: нужно true или false.') % {'field': field})
                changes[field] = request.data[field]
        if not changes:
            raise ParseError(gettext('Укажите is_resolved или is_pinned.'))
        if 'is_pinned' in changes and not author:
            raise PermissionDenied(gettext('Закреплять обсуждения может только автор курса.'))
        if 'is_resolved' in changes and not (author or thread.starter_id == request.user.id):
            raise PermissionDenied(gettext('Отметить обсуждение решённым может только тот, кто его начал, или автор курса.'))

        if 'is_resolved' in changes:
            thread.is_resolved = changes['is_resolved']
            thread.resolved_by = request.user if thread.is_resolved else None
        if 'is_pinned' in changes:
            thread.is_pinned = changes['is_pinned']
        thread.save(update_fields=['is_resolved', 'resolved_by', 'is_pinned'])
        thread = discussion_threads().get(pk=thread.pk)
        context = discussion_context(request, thread.block, thread_comment_ids(thread))
        return Response(ThreadSerializer(thread, context=context).data)

    def delete(self, request, thread_id):
        thread = visible_thread(request, thread_id)
        if not is_course_author(request.user, thread.block):
            raise PermissionDenied(gettext('Удалять обсуждения может только автор курса.'))
        thread.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ThreadCommentsView(APIView):
    """
    POST /api/threads/<id>/comments/   Body: {"text": "..."}: reply

    201: the comment (CommentSerializer). 400: empty / too long text.
    403: banned by the course author. 404: a thread the user can't read.
    429: as for a new thread.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, thread_id):
        thread = visible_thread(request, thread_id)
        text = clean_text(request.data.get('text'))
        check_not_banned(request.user, thread.block)
        check_post_interval(request.user, thread.block)
        comment = Comment.objects.create(thread=thread, user=request.user, text=text)
        context = discussion_context(request, thread.block, [comment.id])
        return Response(CommentSerializer(comment, context=context).data, status=status.HTTP_201_CREATED)


def visible_comment(request, comment_id):
    """A comment in a thread the user may read, else 404."""
    comment = (Comment.objects.select_related('user', 'thread__block__lesson__course')
               .filter(pk=comment_id, thread__in=Thread.objects.visible_to(request.user)).first())
    if comment is None:
        raise NotFound(gettext('Сообщение не найдено.'))
    return comment


class CommentDetailView(APIView):
    """
    DELETE /api/comments/<id>/   the course author removes a comment

    Soft: the comment stays in its thread marked deleted, and its text is no
    longer sent to anyone but the course author. 200: the comment.
    403: not the course author. 404: a comment the user can't read.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, comment_id):
        comment = visible_comment(request, comment_id)
        block = comment.thread.block
        if not is_course_author(request.user, block):
            raise PermissionDenied(gettext('Удалять сообщения может только автор курса.'))
        if not comment.is_deleted:
            comment.is_deleted = True
            comment.deleted_by = request.user
            comment.save(update_fields=['is_deleted', 'deleted_by'])
        return Response(CommentSerializer(comment, context=discussion_context(request, block, [comment.id])).data)


class CommentReportView(APIView):
    """
    POST /api/comments/<id>/report/   a student flags a comment for the course author

    Once per comment and user: 201 the first time, 200 after (the comment,
    with reported: true). 400: own, deleted, or the course author's comment.
    403: the course author (she deletes or bans instead). 404: a comment the
    user can't read.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, comment_id):
        comment = visible_comment(request, comment_id)
        block = comment.thread.block
        if is_course_author(request.user, block):
            raise PermissionDenied(gettext('Автор курса не отправляет жалобы: он может удалить сообщение.'))
        if comment.user_id == request.user.id:
            raise ParseError(gettext('Нельзя пожаловаться на своё сообщение.'))
        if comment.user_id == block.lesson.course.author_id:
            raise ParseError(gettext('Это сообщение автора курса: жалобы на него некому разбирать.'))
        if comment.is_deleted:
            raise ParseError(gettext('Сообщение уже удалено.'))
        _, created = CommentReport.objects.get_or_create(comment=comment, reporter=request.user)
        return Response(CommentSerializer(comment, context=discussion_context(request, block, [comment.id])).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CommentDismissReportsView(APIView):
    """
    POST /api/comments/<id>/dismiss-reports/   the course author: nothing wrong here

    Closes the comment's open reports (they stay, dismissed). 200: the
    comment. 403: not the course author. 404: a comment the user can't read.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, comment_id):
        comment = visible_comment(request, comment_id)
        block = comment.thread.block
        if not is_course_author(request.user, block):
            raise PermissionDenied(gettext('Жалобы разбирает только автор курса.'))
        comment.reports.filter(is_dismissed=False).update(is_dismissed=True)
        return Response(CommentSerializer(comment, context=discussion_context(request, block, [comment.id])).data)


class DiscussionReportsView(APIView):
    """
    GET /api/discussions/reports/   open reports in my courses (course author)

    {"reports": [{"comment": CommentSerializer, "report_count": N,
    "last_reported_at", "thread_id", "block_id", "block_type", "lesson_id",
    "lesson_title", "course_id", "course_title"}]}: one entry per reported
    comment, latest report first. Empty for anyone without courses.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        rows = (open_reports().filter(comment__thread__block__lesson__course__author=request.user)
                .order_by().values('comment')
                .annotate(n=models.Count('id'), last=models.Max('created_at'))
                .order_by('-last', '-comment'))
        counts = {row['comment']: row for row in rows}
        comments = (Comment.objects.filter(pk__in=counts)
                    .select_related('user', 'thread__block__lesson__course').in_bulk())
        banned = set(DiscussionBan.objects.filter(author=request.user).values_list('user_id', flat=True))
        reports = []
        for comment_id, row in counts.items():
            comment = comments[comment_id]
            block = comment.thread.block
            context = {'request': request, 'course_author_id': request.user.id,
                       'report_counts': {comment_id: row['n']}, 'banned_ids': banned}
            reports.append({
                'comment': CommentSerializer(comment, context=context).data,
                'report_count': row['n'],
                'last_reported_at': row['last'],
                'thread_id': comment.thread_id,
                'block_id': str(block.id),
                'block_type': block.type,
                'lesson_id': str(block.lesson_id),
                'lesson_title': block.lesson.title,
                'course_id': str(block.lesson.course_id),
                'course_title': block.lesson.course.title,
            })
        return Response({'reports': reports})


def ban_entry(ban):
    return {'user_id': ban.user_id, 'user_name': display_name(ban.user), 'username': ban.user.username,
            'created_at': ban.created_at}


class DiscussionBansView(APIView):
    """
    GET  /api/discussions/bans/   users I (a course author) have banned
    POST /api/discussions/bans/   Body: {"user_id": N}: ban one

    A banned user can't start threads or reply in any of my courses but can
    still read them. POST 201 (200 if already banned): {user_id, user_name,
    username, created_at}. 400: bad user_id, or myself. 403: I have no
    courses. 404: not a student enrolled in one of my courses.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bans = DiscussionBan.objects.filter(author=request.user).select_related('user')
        return Response({'bans': [ban_entry(ban) for ban in bans]})

    def post(self, request):
        try:
            user_id = int(request.data.get('user_id'))
        except (TypeError, ValueError):
            raise ParseError(gettext('Укажите пользователя: user_id.'))
        if not Course.objects.filter(author=request.user).exists():
            raise PermissionDenied(gettext('Блокировать в обсуждениях может только автор курса.'))
        if user_id == request.user.id:
            raise ParseError(gettext('Нельзя заблокировать себя.'))
        if not Enrollment.objects.filter(student_id=user_id, course__author=request.user).exists():
            raise NotFound(gettext('Среди учащихся ваших курсов такого нет.'))
        ban, created = DiscussionBan.objects.get_or_create(author=request.user, user_id=user_id)
        ban = DiscussionBan.objects.select_related('user').get(pk=ban.pk)
        return Response(ban_entry(ban), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class DiscussionBanDetailView(APIView):
    """
    DELETE /api/discussions/bans/<user_id>/   lift my ban. 204; 404: no such ban.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, user_id):
        deleted, _ = DiscussionBan.objects.filter(author=request.user, user_id=user_id).delete()
        if not deleted:
            raise NotFound(gettext('Этот пользователь не заблокирован.'))
        return Response(status=status.HTTP_204_NO_CONTENT)


class DiscussionCountsView(APIView):
    """
    GET /api/discussions/counts/?lesson=<id>

    {"counts": {"<block id>": N}}: for each task block of the lesson that has
    any, the number of threads the user may read (the «💬 N» badges); the
    course author also gets {"reports": {"<block id>": N}}, open reports.
    400: lesson missing or malformed. 404: a lesson the user can't read.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            lesson_id = uuid.UUID(str(request.query_params.get('lesson')))
        except ValueError:
            raise ParseError(gettext('Укажите урок: lesson.'))
        lesson = Lesson.objects.visible_to(request.user).select_related('course').filter(pk=lesson_id).first()
        if lesson is None:
            raise NotFound(gettext('Урок не найден.'))
        rows = (Thread.objects.visible_to(request.user).filter(block__lesson=lesson)
                .order_by().values('block').annotate(n=models.Count('id')))
        data = {'counts': {str(row['block']): row['n'] for row in rows}}
        if lesson.course.author_id == request.user.id:
            reports = (open_reports().filter(comment__thread__block__lesson=lesson)
                       .order_by().values('comment__thread__block').annotate(n=models.Count('id')))
            data['reports'] = {str(row['comment__thread__block']): row['n'] for row in reports}
        return Response(data)
