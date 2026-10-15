"""
Authentication Views for the Learning Platform

Provides:
- User registration (with an emailed confirmation link)
- Email confirmation and resending the link
- Login (get JWT tokens; only for confirmed addresses)
- Get current user info
- Logout (client-side token deletion)
"""

from urllib.parse import urlencode

from django.conf import settings
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.utils import timezone, translation
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import (
    MinimumLengthValidator, get_default_password_validators, validate_password)
from django.core.exceptions import ValidationError as DjangoValidationError
from .email_confirmation import (
    confirm_email, normalize_email, safe_next, send_account_exists_email, send_confirmation_email)
from .serializers import UserSerializer
from .throttles import RegisterThrottle, ResendConfirmationEmailThrottle, ResendConfirmationThrottle

User = get_user_model()


# =============================================================================
# REGISTER (Sign Up)
# =============================================================================

def _min_password_length():
    """min_length of the configured MinimumLengthValidator (None if it's not enabled)."""
    for validator in get_default_password_validators():
        if isinstance(validator, MinimumLengthValidator):
            return validator.min_length
    return None


def _register_error(message, code, **extra):
    """400 for the register form. `code` lets the client show its own wording."""
    return Response({'error': message, 'code': code, **extra}, status=status.HTTP_400_BAD_REQUEST)


def _registered(email):
    """The one sign-up answer, whether or not the address already had an account
    (no way to tell from outside which addresses are registered)."""
    return Response({
        'detail': f'Мы отправили письмо на {email}. Откройте ссылку из письма, чтобы подтвердить адрес и войти.',
        'email': email,
    }, status=status.HTTP_201_CREATED)


def _email_language(request):
    """Language for emails: the site's language cookie (RU/EN switch on the public
    pages), else the browser's Accept-Language, else Russian. Not the active
    language: /api/ has no /en/ prefix, so Django always activates Russian there."""
    return translation.get_language_from_request(request)


def _is_true(value):
    return value is True or str(value).lower() in ('true', '1', 'on', 'yes')


@api_view(['POST'])
@authentication_classes([])  # never authenticates: a stale token in the header can't 401 sign-up
@permission_classes([AllowAny])  # Anyone can register
@throttle_classes([RegisterThrottle])  # it sends an email: limited per IP
def register_view(request):
    """
    Register a new STUDENT account and email a confirmation link. Any "role" in
    the body is ignored; authors and admins are created in the Django admin.
    No tokens: the account can log in once the address is confirmed.

    POST /api/auth/register/

    Body:
    {
        "username": "alice",
        "email": "alice@example.com",
        "password": "password123",
        "accept_privacy": true,
        "next": "/enroll/<id>/"   (optional: where to continue after login)
    }

    Returns 201 {"detail": "...", "email": "alice@example.com"}. The same 201
    when the address already has an account: then no account is created and the
    address's owner gets an "you already have an account" email instead.

    Errors (400): {"error": "...", "code": ...}, code is one of
    "required" (+ "fields"), "privacy_required", "invalid_username",
    "invalid_email", "username_taken", "weak_password" (+ "codes" and
    "messages" from Django's AUTH_PASSWORD_VALIDATORS, and "min_length" from
    MinimumLengthValidator). 429 when the IP has registered too often.
    """
    username = (request.data.get('username') or '').strip()
    email = normalize_email(request.data.get('email'))
    password = request.data.get('password') or ''
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')

    missing = [name for name, value in (('username', username), ('email', email), ('password', password))
               if not value]
    if missing:
        return _register_error('Заполните имя пользователя, почту и пароль.', 'required', fields=missing)

    if not _is_true(request.data.get('accept_privacy')):
        return _register_error('Нужно согласие с политикой обработки персональных данных.', 'privacy_required')

    try:
        User.username_validator(username)
    except DjangoValidationError:
        return _register_error('Недопустимое имя пользователя.', 'invalid_username')

    try:
        validate_email(email)
    except DjangoValidationError:
        return _register_error('Введите правильный адрес почты.', 'invalid_email')

    # Case-insensitive: "Alice" can't sign up next to "alice" (login stays exact).
    if User.objects.filter(username__iexact=username).exists():
        return _register_error('Это имя пользователя уже занято.', 'username_taken')

    # The project's AUTH_PASSWORD_VALIDATORS (length, common, numeric, similar to username).
    try:
        validate_password(password, user=User(username=username, email=email))
    except DjangoValidationError as exc:
        return _register_error(
            'Слишком простой пароль.', 'weak_password',
            codes=[e.code for e in exc.error_list],
            messages=list(exc.messages),
            min_length=_min_password_length(),
        )

    language = _email_language(request)
    existing = User.objects.filter(email__iexact=email).first()
    if existing is None:
        try:
            with transaction.atomic():
                # Role is fixed: never taken from the request.
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,  # Django automatically hashes password
                    role='STUDENT',
                    first_name=first_name,
                    last_name=last_name,
                    email_verified=False,
                    accepted_privacy_at=timezone.now(),
                    privacy_version=settings.PRIVACY_POLICY_VERSION,
                )
        except IntegrityError:
            # A simultaneous sign-up took the address (or the username) first.
            existing = User.objects.filter(email__iexact=email).first()
            if existing is None:
                return _register_error('Это имя пользователя уже занято.', 'username_taken')
        else:
            send_confirmation_email(user, language, request.data.get('next'))
            return _registered(email)

    send_account_exists_email(existing, language)
    return _registered(email)


# =============================================================================
# EMAIL CONFIRMATION
# =============================================================================

def confirm_email_view(request):
    """
    GET /api/auth/confirm-email/?token=...  (the link in the confirmation email)

    Confirms the address and redirects to the login page, which shows the
    result: /login/?confirm=ok | expired | invalid | used (plus the local
    ?next= path from sign-up, if any). Works in any browser: the token alone
    identifies the account.
    """
    query = {'confirm': confirm_email(request.GET.get('token'))}
    if safe_next(request.GET.get('next')):
        query['next'] = safe_next(request.GET.get('next'))  # e.g. back to joining a course
    return redirect(f'/login/?{urlencode(query)}')


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ResendConfirmationThrottle, ResendConfirmationEmailThrottle])
def resend_confirmation_view(request):
    """
    POST /api/auth/resend-confirmation/  {"email": "alice@example.com", "next": optional}

    Sends a new confirmation link if the address belongs to an account that
    is not confirmed yet. The answer is the same in every case (no way to tell
    which addresses are registered). 400 without a valid address; 429 after
    3 requests an hour from one IP or for one address.
    """
    email = normalize_email(request.data.get('email'))
    try:
        validate_email(email)
    except DjangoValidationError:
        return Response({'error': 'Введите правильный адрес почты.', 'code': 'invalid_email'},
                        status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(email__iexact=email, email_verified=False, is_active=True).first()
    if user is not None:
        send_confirmation_email(user, _email_language(request), request.data.get('next'))
    return Response({
        'detail': 'Если этот адрес зарегистрирован и ещё не подтверждён, мы отправили на него новое письмо.',
    })


# =============================================================================
# LOGIN (Get Tokens)
# =============================================================================

@api_view(['POST'])
@permission_classes([AllowAny])  # Anyone can attempt login
def login_view(request):
    """
    Login user and get JWT tokens.

    POST /api/auth/login/

    Body:
    {
        "username": "alice",
        "password": "password123"
    }

    Returns:
    {
        "user": {...},
        "tokens": {
            "access": "...",
            "refresh": "..."
        }
    }

    403 {"code": "email_not_verified", "error": "...", "email": "..."} for a
    correct password on an unconfirmed account: the client offers to resend
    the link (/api/auth/resend-confirmation/) to that address.
    """
    from django.contrib.auth import authenticate

    username = request.data.get('username')
    password = request.data.get('password')

    # Validation
    if not username or not password:
        return Response(
            {'error': 'Username and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Authenticate user
    user = authenticate(username=username, password=password)

    if user is None:
        return Response(
            {'error': 'Invalid credentials'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Check if user is active
    if not user.is_active:
        return Response(
            {'error': 'User account is disabled'},
            status=status.HTTP_403_FORBIDDEN
        )

    # Only after the password checked out: the address is the user's own.
    if not user.email_verified:
        return Response(
            {'error': 'Подтвердите адрес почты', 'code': 'email_not_verified', 'email': user.email},
            status=status.HTTP_403_FORBIDDEN
        )

    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)

    return Response({
        'user': UserSerializer(user).data,
        'tokens': {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
    })


# =============================================================================
# GET CURRENT USER
# =============================================================================

from rest_framework_simplejwt.authentication import JWTAuthentication

@api_view(['GET'])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])  # Must be logged in
def current_user_view(request):
    """
    Get current logged-in user info.

    GET /api/auth/me/

    Headers:
    Authorization: Bearer <access_token>

    Returns:
    {
        "id": "...",
        "username": "alice",
        "email": "alice@example.com",
        "role": "STUDENT",
        ...
    }
    """
    serializer = UserSerializer(request.user)
    response = Response(serializer.data)
    # Prevent browsers from caching this response — a cached /auth/me/ response
    # from a previous user would be served to the next user even after re-login.
    response['Cache-Control'] = 'no-store, private'
    response['Vary'] = 'Authorization'
    return response


# =============================================================================
# LOGOUT
# =============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Logout user.

    POST /api/auth/logout/

    Note: With JWT, logout is handled client-side by deleting the token.
    This endpoint is optional but can be used to blacklist tokens if needed.

    For now, it just returns success. Client should delete the token.
    """
    return Response({
        'message': 'Successfully logged out. Please delete your token.'
    })

# =============================================================================
# REFRESH TOKEN
# =============================================================================

# Note: Token refresh is handled automatically by simplejwt
# Endpoint: POST /api/auth/token/refresh/
# Body: {"refresh": "your-refresh-token"}
# Returns: {"access": "new-access-token"}