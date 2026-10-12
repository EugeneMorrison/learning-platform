"""
Authentication Views for the Learning Platform

Provides:
- User registration
- Login (get JWT tokens)
- Get current user info
- Logout (client-side token deletion)
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import (
    MinimumLengthValidator, get_default_password_validators, validate_password)
from django.core.exceptions import ValidationError as DjangoValidationError
from .serializers import UserSerializer

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


@api_view(['POST'])
@authentication_classes([])  # never authenticates: a stale token in the header can't 401 sign-up
@permission_classes([AllowAny])  # Anyone can register
def register_view(request):
    """
    Register a new user and log them in. Public registration always creates
    a STUDENT: any "role" in the body is ignored. Authors and admins are
    created only in the Django admin.

    POST /api/auth/register/

    Body:
    {
        "username": "alice",
        "email": "alice@example.com",
        "password": "password123"
    }

    Returns 201, same shape as login:
    {
        "user": {...},
        "tokens": {
            "access": "...",
            "refresh": "..."
        }
    }

    Errors (400): {"error": "...", "code": ...}, code is one of
    "required" (+ "fields"), "invalid_username", "username_taken",
    "email_taken", "weak_password" (+ "codes" and "messages" from Django's
    AUTH_PASSWORD_VALIDATORS, and "min_length" from MinimumLengthValidator).
    """
    # Get data from request
    username = (request.data.get('username') or '').strip()
    email = request.data.get('email')
    password = request.data.get('password') or ''
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')

    # Validation
    missing = [name for name, value in (('username', username), ('password', password)) if not value]
    if missing:
        return _register_error('Username and password are required', 'required', fields=missing)

    try:
        User.username_validator(username)
    except DjangoValidationError:
        return _register_error('Invalid username', 'invalid_username')

    # Case-insensitive: "Alice" can't sign up next to "alice" (login stays exact).
    if User.objects.filter(username__iexact=username).exists():
        return _register_error('Username already exists', 'username_taken')

    # The project's AUTH_PASSWORD_VALIDATORS (length, common, numeric, similar to username).
    try:
        validate_password(password, user=User(username=username, email=email or ''))
    except DjangoValidationError as exc:
        return _register_error(
            'Password is too weak', 'weak_password',
            codes=[e.code for e in exc.error_list],
            messages=list(exc.messages),
            min_length=_min_password_length(),
        )

    # Check if email already exists
    if email and User.objects.filter(email=email).exists():
        return _register_error('Email already exists', 'email_taken')

    # Create user. Role is fixed: never taken from the request.
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,  # Django automatically hashes password
        role='STUDENT',
        first_name=first_name,
        last_name=last_name
    )

    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)

    # Return user data + tokens
    return Response({
        'user': UserSerializer(user).data,
        'tokens': {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
    }, status=status.HTTP_201_CREATED)


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