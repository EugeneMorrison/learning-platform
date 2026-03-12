"""
Main URL Configuration for Learning Platform

Includes:
- Admin panel: /admin/
- API endpoints: /api/
- Auth endpoints: /api/auth/
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('api.auth_urls')),  # JWT auth endpoints
    path('api/', include('api.urls')),            # API endpoints
    path('api-auth/', include('rest_framework.urls')),  # login/logout in browsable API,
    ]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
