"""
Main URL Configuration for Learning Platform

Includes:
- Landing page: / (Russian) and /en/ (English), rendered by Django
- Course page: /course/<slug>/ and /en/course/<slug>/ (Django)
- About me ("Обо мне"): /about/ and /en/about/ (Django)
- Language switch: /i18n/setlang/ (Django's set_language view)
- Admin panel: /admin/
- API endpoints: /api/
- Auth endpoints: /api/auth/
- Lesson viewer: /lesson/<uuid>/ (serves React app, embeddable via iframe)
- Login / register: /login/, /register/ (React app; ?next= validated first)
"""

from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import path, include, re_path
from django.shortcuts import redirect, render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.static import serve
from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme

from .views import about_view, course_detail_view, favicon_view, landing_view


@xframe_options_exempt
def lesson_view(request, lesson_id):
    """
    Serve React index.html for any /lesson/<uuid>/ URL.
    React reads the UUID from window.location.pathname and loads the lesson.
    @xframe_options_exempt allows this page to be embedded in an <iframe>.
    """
    return render(request, 'index.html')


def spa_view(request):
    return render(request, 'index.html')


def auth_page_view(request):
    """
    /login/ and /register/: the React pages, after a server-side check of ?next=
    (where to go after logging in; the course page sends anonymous visitors here
    with next=<its own path>). A next that points to another host or scheme is
    an open redirect: drop it by redirecting to the bare page. React checks the
    value again (frontend/src/lib/safeNext.js).
    """
    next_url = request.GET.get('next')
    if next_url is not None and not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(request.path)
    return render(request, 'index.html')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('api.auth_urls')),  # JWT auth endpoints
    path('api/', include('api.urls')),            # API endpoints
    path('api-auth/', include('rest_framework.urls')),  # login/logout in browsable API
    path('lesson/<uuid:lesson_id>/', lesson_view, name='lesson-viewer'),  # React SPA
    # Serve author-uploaded media (lesson images). Explicit serve() works under
    # Daphne regardless of DEBUG; must come before the SPA catch-all below.
    # TEMPORARY: Django serving media is a stopgap until Caddy serves /media/.
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    path('i18n/', include('django.conf.urls.i18n')),  # set_language for the RU/EN switch
    path('favicon.ico', favicon_view, name='favicon'),  # before the SPA catch-all
    path('login/', auth_page_view, name='spa-login'),        # React pages, ?next= checked
    path('register/', auth_page_view, name='spa-register'),
]

# Django-rendered public pages. Russian has no prefix (/), English gets /en/.
# Must come before the SPA catch-all, which would otherwise answer at /.
urlpatterns += i18n_patterns(
    path('', landing_view, name='landing'),
    path('course/<slug:slug>/', course_detail_view, name='course_detail'),
    path('about/', about_view, name='about'),
    prefix_default_language=False,
)

urlpatterns += [
    # Catch-all for client-side React Router routes (/login/, /register/, /dashboard/, /courses/...)
    # Must be last — Django checks urlpatterns in order, so this only matches what nothing above did.
    re_path(r'^(?!api/|admin/|api-auth/|media/|static/).*$', spa_view, name='spa-fallback'),
]

# Static files are served automatically by 'django.contrib.staticfiles' during development.
# No manual static() call needed — runserver handles all STATICFILES_DIRS entries.
