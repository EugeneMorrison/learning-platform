"""
Authentication URL Configuration

Provides auth endpoints:
- POST /api/auth/register/       - Register new user (emails a confirmation link)
- GET  /api/auth/confirm-email/  - The emailed link: confirm, redirect to /login/
- POST /api/auth/resend-confirmation/ - Email a new confirmation link
- POST /api/auth/login/          - Login and get tokens
- GET  /api/auth/me/             - Get current user info
- POST /api/auth/logout/         - Logout
- POST /api/auth/token/refresh/  - Refresh access token
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import auth_views

urlpatterns = [
    # Custom auth endpoints
    path('register/', auth_views.register_view, name='register'),
    path('confirm-email/', auth_views.confirm_email_view, name='confirm-email'),
    path('resend-confirmation/', auth_views.resend_confirmation_view, name='resend-confirmation'),
    path('login/', auth_views.login_view, name='login'),
    path('me/', auth_views.current_user_view, name='current-user'),
    path('logout/', auth_views.logout_view, name='logout'),

    # JWT token refresh (built-in)
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]