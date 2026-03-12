"""
Authentication Views for the Learning Platform

Provides:
- User registration
- Login (get JWT tokens)
- Get current user info
- Logout (client-side token deletion)
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from .serializers import UserSerializer

User = get_user_model()


# =============================================================================
# REGISTER (Sign Up)
# =============================================================================

@api_view(['POST'])
@permission_classes([AllowAny])  # Anyone can register
def register_view(request):
    """
    Register a new user.

    POST /api/auth/register/

    Body:
    {
        "username": "alice",
        "email": "alice@example.com",
        "password": "password123",
        "role": "STUDENT"  # or "AUTHOR"
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
    # Get data from request
    username = request.data.get('username')
    email = request.data.get('email')
    password = request.data.get('password')
    role = request.data.get('role', 'STUDENT')  # Default to STUDENT
    first_name = request.data.get('first_name', '')
    last_name = request.data.get('last_name', '')

    # Validation
    if not username:
        return Response(
            {'error': 'Username is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not password:
        return Response(
            {'error': 'Password is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check if username already exists
    if User.objects.filter(username=username).exists():
        return Response(
            {'error': 'Username already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check if email already exists
    if email and User.objects.filter(email=email).exists():
        return Response(
            {'error': 'Email already exists'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Validate role
    valid_roles = ['STUDENT', 'AUTHOR', 'ADMIN']
    if role not in valid_roles:
        return Response(
            {'error': f'Role must be one of: {valid_roles}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Create user
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,  # Django automatically hashes password
        role=role,
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

@api_view(['GET'])
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
    return Response(serializer.data)


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