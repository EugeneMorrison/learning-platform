from django.db import transaction
from django.db.models import Avg
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .completion import course_completed
from .models import Course, CourseReview, Enrollment


class ReviewSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='student.username', read_only=True)
    course_title = serializers.CharField(source='course.title', read_only=True)
    rating = serializers.IntegerField(min_value=1, max_value=5)

    class Meta:
        model = CourseReview
        fields = ['id', 'course', 'course_title', 'username', 'rating', 'text', 'status', 'revision', 'published_at']
        read_only_fields = ['id', 'course', 'status', 'revision', 'published_at']


def moderation_scope(user):
    reviews = CourseReview.objects.select_related('student', 'course')
    if user.is_staff and user.has_perm('api.moderate_coursereview'):
        return reviews
    return reviews.filter(course__author=user)


class CourseReviewsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, course_id):
        course = get_object_or_404(Course.objects.visible_to(request.user), pk=course_id)
        reviews = course.student_reviews.filter(status='approved').select_related('student', 'course').order_by('-published_at', '-pk')
        return Response({'average': reviews.aggregate(value=Avg('rating'))['value'],
                         'count': reviews.count(), 'reviews': ReviewSerializer(reviews, many=True).data})


class MyCourseReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, course_id):
        course = get_object_or_404(Course.objects.visible_to(request.user), pk=course_id)
        review = CourseReview.objects.filter(course=course, student=request.user).first()
        eligible = (request.user.role == 'STUDENT' and Enrollment.objects.filter(course=course, student=request.user).exists()
                    and course_completed(request.user, course))
        return Response({'eligible': eligible, 'review': ReviewSerializer(review).data if review else None})

    @transaction.atomic
    def put(self, request, course_id):
        # Lock the enrollment to serialize first submissions as well as edits.
        enrollment = get_object_or_404(Enrollment.objects.select_for_update().select_related('course'),
                                       course_id=course_id, student=request.user)
        if request.user.role != 'STUDENT' or not course_completed(request.user, enrollment.course):
            raise PermissionDenied('Для отзыва необходимо пройти не менее 89% заданий курса.')
        existing = CourseReview.objects.select_for_update().filter(course_id=course_id, student=request.user).first()
        serializer = ReviewSerializer(existing, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(course_id=course_id, student=request.user, status='pending', published_at=None,
                        revision=existing.revision + 1 if existing else 1)
        return Response(serializer.data)


class ReviewModerationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        reviews = moderation_scope(request.user).filter(status='pending').order_by('updated_at', 'pk')
        return Response(ReviewSerializer(reviews, many=True).data)

    @transaction.atomic
    def post(self, request):
        review_id = serializers.IntegerField(min_value=1).run_validation(request.data.get('id'))
        review = get_object_or_404(moderation_scope(request.user).select_for_update(), pk=review_id)
        if request.data.get('status') not in ('approved', 'rejected'):
            raise serializers.ValidationError({'status': 'Выберите approved или rejected.'})
        if review.status != 'pending' or request.data.get('revision') != review.revision:
            return Response({'detail': 'Отзыв изменён. Обновите список перед модерацией.'}, status=409)
        review.status = request.data['status']
        review.published_at = timezone.now() if review.status == 'approved' else None
        review.save()
        return Response(ReviewSerializer(review).data)
