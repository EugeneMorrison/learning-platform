"""
Main URL Configuration for Learning Platform

Includes:
- Admin panel: /admin/
- API endpoints: /api/
- Auth endpoints: /api/auth/
- Lesson viewer: /lesson/<uuid>/ (serves React app, embeddable via iframe)
"""

from django.contrib import admin
from django.urls import path, include
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt


@xframe_options_exempt
def lesson_view(request, lesson_id):
    """
    Serve React index.html for any /lesson/<uuid>/ URL.
    React reads the UUID from window.location.pathname and loads the lesson.
    @xframe_options_exempt allows this page to be embedded in an <iframe>.
    """
    return render(request, 'index.html')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('api.auth_urls')),  # JWT auth endpoints
    path('api/', include('api.urls')),            # API endpoints
    path('api-auth/', include('rest_framework.urls')),  # login/logout in browsable API
    path('lesson/<uuid:lesson_id>/', lesson_view, name='lesson-viewer'),  # React SPA
    ]

# Static files are served automatically by 'django.contrib.staticfiles' during development.
# No manual static() call needed — runserver handles all STATICFILES_DIRS entries.
