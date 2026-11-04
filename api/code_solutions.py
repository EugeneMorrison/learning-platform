"""Accepted code is shared only with people who have solved that same task."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Block, Progress
from .serializers import display_name


class SolutionsPagination(LimitOffsetPagination):
    default_limit = 10
    max_limit = 20


class CodeSolutionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, block_id):
        block = get_object_or_404(
            Block.objects.visible_to(request.user).select_related('lesson__course__author'),
            pk=block_id,
        )
        if block.type != 'CODE':
            raise ParseError('Другие решения доступны только для задач с кодом.')
        if not Progress.objects.filter(block=block, student=request.user, is_correct=True).exists():
            raise PermissionDenied('Сначала решите задачу, чтобы посмотреть другие решения.')

        author = block.lesson.course.author
        official = block.content.get('solution')
        official_solution = (
            {'code': official, 'author_name': display_name(author)}
            if isinstance(official, str) and official.strip() else None
        )
        # Progress retains the first accepted answer, even after failed practice
        # attempts. Exclude the viewer and the author's own test submissions.
        submissions = (Progress.objects.filter(block=block, is_correct=True, answer__code__isnull=False)
                       .exclude(student__in=[request.user, author])
                       .select_related('student').order_by('-created_at', '-id'))
        paginator = SolutionsPagination()
        page = paginator.paginate_queryset(submissions, request, view=self)
        results = []
        for submission in page:
            answer = submission.answer
            code = answer.get('code') if isinstance(answer, dict) else None
            if isinstance(code, str) and code.strip():
                results.append({'id': str(submission.pk), 'code': code,
                                'author_name': display_name(submission.student)})
        next_offset = paginator.offset + paginator.limit
        return Response({
            'official_solution': official_solution,
            'results': results,
            'next_offset': next_offset if next_offset < paginator.count else None,
        })
