"""
URL routing for API endpoints
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Router automatically creates URLs for ViewSets
# Example: router.register('courses', CourseViewSet) creates:
# - GET    /api/courses/           → list()
# - POST   /api/courses/           → create()
# - GET    /api/courses/{id}/      → retrieve()
# - PUT    /api/courses/{id}/      → update()
# - PATCH  /api/courses/{id}/      → partial_update()
# - DELETE /api/courses/{id}/      → destroy()

router = DefaultRouter()
router.register(r'courses', views.CourseViewSet, basename='course')
router.register(r'lessons', views.LessonViewSet, basename='lesson')
router.register(r'blocks', views.BlockViewSet, basename='block')
router.register(r'enrollments', views.EnrollmentViewSet, basename='enrollment')
router.register(r'progress', views.ProgressViewSet, basename='progress')

urlpatterns = [
    # Simple test endpoints
    path('hello/', views.hello_view, name='hello'),
    path('status/', views.status_view, name='status'),
    path('run-code/', views.RunCodeView.as_view(), name='run-code'),
    path('run-tests/', views.RunTestsView.as_view(), name='run-tests'),
    path('enrollments/', views.EnrollmentListCreateView.as_view(), name='enrollment-list'),
    path('enrollments/<uuid:course_id>/', views.EnrollmentDeleteView.as_view(), name='enrollment-delete'),
    path('courses/<uuid:course_id>/enrollments/', views.CourseEnrollmentsView.as_view(), name='course-enrollments'),

    path('progress/submit/', views.ProgressSubmitView.as_view(), name='progress-submit'),
    path('progress/course/<uuid:course_id>/', views.ProgressCourseView.as_view(), name='progress-course'),
    path('progress/stats/', views.ProgressStatsView.as_view(), name='progress-stats'),

    # Router URLs (all the ViewSets)
    path('', include(router.urls)),
]

"""
Available Endpoints:

COURSES:
- GET    /api/courses/              → List all published courses
- POST   /api/courses/              → Create course (author only)
- GET    /api/courses/{id}/         → Get course details
- PUT    /api/courses/{id}/         → Update course (owner only)
- DELETE /api/courses/{id}/         → Delete course (owner only)
- GET    /api/courses/my_courses/   → My courses (author only)
- POST   /api/courses/{id}/publish/ → Toggle publish status

LESSONS:
- GET    /api/lessons/              → List lessons
- GET    /api/lessons/?course={id}  → Lessons for specific course
- POST   /api/lessons/              → Create lesson (author only)
- GET    /api/lessons/{id}/         → Get lesson details
- PUT    /api/lessons/{id}/         → Update lesson (owner only)
- DELETE /api/lessons/{id}/         → Delete lesson (owner only)

BLOCKS:
- GET    /api/blocks/               → List blocks
- GET    /api/blocks/?lesson={id}   → Blocks for specific lesson
- POST   /api/blocks/               → Create block (author only)
- GET    /api/blocks/{id}/          → Get block details
- PUT    /api/blocks/{id}/          → Update block (owner only)
- DELETE /api/blocks/{id}/          → Delete block (owner only)

ENROLLMENTS:
- GET    /api/enrollments/          → My enrollments
- POST   /api/enrollments/enroll/   → Enroll in course
- DELETE /api/enrollments/{id}/     → Unenroll

PROGRESS:
- GET    /api/progress/             → My progress
- POST   /api/progress/submit/      → Submit block completion
"""