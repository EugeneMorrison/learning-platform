"""Student course sections, resume destinations and follow-up recommendations."""
from django.db.models import Case, Count, F, IntegerField, OuterRef, Q, Subquery, UUIDField, Value, When
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .block_content import TASK_TYPES
from .completion import meets_completion
from .models import Attempt, Course, Enrollment, Lesson, Progress


def course_totals(user):
    tasks = Q(lessons__blocks__type__in=TASK_TYPES)
    return Course.objects.annotate(
        task_count=Count('lessons__blocks', filter=tasks, distinct=True),
        solved_count=Count('lessons__blocks', distinct=True, filter=tasks & Q(
            lessons__blocks__progress__student=user,
            lessons__blocks__progress__is_correct=True)),
    )


class StudentDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        attempts = Attempt.objects.filter(
            student=request.user, block__lesson__course=OuterRef('course_id')
        ).order_by('-created_at', '-pk')
        progress = Progress.objects.filter(
            student=request.user, block__lesson__course=OuterRef('course_id')
        ).order_by('-updated_at', '-pk')
        first_lesson = Lesson.objects.filter(course=OuterRef('course_id')).order_by('order_index', 'pk')
        enrollments = list(Enrollment.objects.filter(student=request.user).annotate(
            attempt_at=Subquery(attempts.values('created_at')[:1]),
            attempt_lesson=Subquery(attempts.values('block__lesson_id')[:1], output_field=UUIDField()),
            progress_at=Subquery(progress.values('updated_at')[:1]),
            progress_lesson=Subquery(progress.values('block__lesson_id')[:1], output_field=UUIDField()),
            first_lesson=Subquery(first_lesson.values('pk')[:1]),
        ))
        courses = {c.pk: c for c in course_totals(request.user).filter(
            pk__in=[e.course_id for e in enrollments])}
        in_progress, completed = [], []

        def metadata(course):
            return dict(id=str(course.pk), title=course.title,
                        cover=request.build_absolute_uri(course.cover.url) if course.cover else None)

        for enrollment in enrollments:
            course = courses[enrollment.course_id]
            activity = [(enrollment.enrolled_at, enrollment.first_lesson)]
            for date, lesson in [(enrollment.last_activity_at, enrollment.last_lesson_id),
                                 (enrollment.attempt_at, enrollment.attempt_lesson),
                                 (enrollment.progress_at, enrollment.progress_lesson)]:
                if date:
                    activity.append((date, lesson or enrollment.first_lesson))
            last_at, last_lesson = max(activity, key=lambda item: item[0])
            # Matches LessonViewerSerializer: no required tasks means complete.
            is_complete = meets_completion(course.solved_count, course.task_count)
            item = metadata(course) | dict(
                completion_percentage=(int(100 * course.solved_count / course.task_count)
                                       if course.task_count else 100),
                last_activity_at=last_at, last_lesson=str(last_lesson) if last_lesson else None,
            )
            (completed if is_complete else in_progress).append(item)
        for section in (in_progress, completed):
            section.sort(key=lambda item: (item['last_activity_at'], item['id']), reverse=True)

        # Include retained progress after an enrollment is revoked. Such completed
        # courses must not reappear as recommendations or lose their follow-ups.
        completed_ids = list(course_totals(request.user).filter(
            lessons__blocks__progress__student=request.user,
        ).filter(solved_count__gte=F('task_count') * 0.89).values_list('pk', flat=True))
        completed_ids += [item['id'] for item in completed]
        followups = Course.objects.filter(recommended_after__pk__in=completed_ids).values('pk')
        candidates = Course.objects.filter(is_published=True).exclude(
            pk__in=[e.course_id for e in enrollments] + completed_ids
        ).annotate(
            popularity=Count('enrollments', distinct=True),
            priority=Case(When(pk__in=followups, then=Value(0)), default=Value(1), output_field=IntegerField()),
        ).order_by('priority', '-popularity', 'title', 'pk')[:6]
        recommended = [metadata(c) | dict(level=c.level, price=str(c.price), slug=c.slug)
                       for c in candidates]
        return Response(dict(in_progress=in_progress, completed=completed, recommended=recommended))
