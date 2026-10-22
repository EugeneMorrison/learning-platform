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

urlpatterns = [
    # Simple test endpoints
    path('hello/', views.hello_view, name='hello'),
    path('status/', views.status_view, name='status'),
    path('run-code/', views.RunCodeView.as_view(), name='run-code'),
    path('run-tests/', views.RunTestsView.as_view(), name='run-tests'),
    path('upload-image/', views.UploadImageView.as_view(), name='upload-image'),
    path('messages/', views.MessageView.as_view(), name='messages'),
    path('messages/unread/', views.UnreadMessagesView.as_view(), name='messages-unread'),
    path('messages/read/', views.MarkReadView.as_view(), name='messages-read'),
    path('questions/', views.QuestionView.as_view(), name='questions'),
    path('questions/preview/', views.QuestionPreviewView.as_view(), name='questions-preview'),
    path('blocks/<uuid:block_id>/threads/', views.BlockThreadsView.as_view(), name='block-threads'),
    path('threads/<int:thread_id>/', views.ThreadDetailView.as_view(), name='thread-detail'),
    path('threads/<int:thread_id>/comments/', views.ThreadCommentsView.as_view(), name='thread-comments'),
    path('comments/<int:comment_id>/', views.CommentDetailView.as_view(), name='comment-detail'),
    path('comments/<int:comment_id>/report/', views.CommentReportView.as_view(), name='comment-report'),
    path('comments/<int:comment_id>/dismiss-reports/', views.CommentDismissReportsView.as_view(),
         name='comment-dismiss-reports'),
    path('discussions/counts/', views.DiscussionCountsView.as_view(), name='discussion-counts'),
    path('discussions/reports/', views.DiscussionReportsView.as_view(), name='discussion-reports'),
    path('discussions/bans/', views.DiscussionBansView.as_view(), name='discussion-bans'),
    path('discussions/bans/<int:user_id>/', views.DiscussionBanDetailView.as_view(), name='discussion-ban-detail'),
    path('enrollments/', views.EnrollmentListCreateView.as_view(), name='enrollment-list'),
    path('enrollments/<uuid:course_id>/', views.EnrollmentDeleteView.as_view(), name='enrollment-delete'),
    path('courses/<uuid:course_id>/enrollments/', views.CourseEnrollmentsView.as_view(), name='course-enrollments'),

    path('progress/submit/', views.ProgressSubmitView.as_view(), name='progress-submit'),
    path('progress/course/<uuid:course_id>/', views.ProgressCourseView.as_view(), name='progress-course'),
    path('progress/stats/', views.ProgressStatsView.as_view(), name='progress-stats'),
    path('progress/student/<int:student_id>/course/<uuid:course_id>/', views.StudentProgressView.as_view(), name='student-progress'),

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
- GET    /api/enrollments/              → My enrollments
- POST   /api/enrollments/              → Self-enrol in a published free course (students only)
- DELETE /api/enrollments/{course_id}/  → Unenroll
- POST   /api/courses/{id}/enroll_student/ → Teacher enrols a student by username

PROGRESS:
- POST   /api/progress/submit/                       → Submit a block answer (enrolled students / course author)
- GET    /api/progress/course/{course_id}/           → My progress in a course
- GET    /api/progress/stats/                        → My stats across enrolled courses
- GET    /api/progress/student/{id}/course/{id}/     → A student's progress (self or course author)

DISCUSSIONS (public threads per task block; api/discussions.py):
- GET    /api/blocks/{id}/threads/            → The block's threads I may read
- POST   /api/blocks/{id}/threads/            → Start a thread
- POST   /api/threads/{id}/comments/          → Reply
- PATCH  /api/threads/{id}/                   → Resolve (starter / course author), pin (course author)
- DELETE /api/threads/{id}/                   → Delete a thread (course author)
- DELETE /api/comments/{id}/                  → Delete a comment, softly (course author)
- GET    /api/discussions/counts/?lesson={id} → Threads I may read, per block (+ open reports: course author)
- POST   /api/comments/{id}/report/           → Report a comment (students)
- POST   /api/comments/{id}/dismiss-reports/  → Dismiss its reports (course author)
- GET    /api/discussions/reports/            → Open reports in my courses (course author)
- GET    /api/discussions/bans/               → Users I banned from posting (course author)
- POST   /api/discussions/bans/               → Ban a student of my courses {"user_id"}
- DELETE /api/discussions/bans/{user_id}/     → Lift a ban
"""