"""
Custom Permissions for Learning Platform

Permission Logic:
- IsAuthor: Only users with role='AUTHOR' can create/edit courses
- IsOwnerOrReadOnly: Authors can only edit THEIR courses
- IsEnrolledStudent: Students can only view courses they're enrolled in
"""

from rest_framework import permissions


# =============================================================================
# AUTHOR PERMISSION (Must be author to create courses)
# =============================================================================

class IsAuthor(permissions.BasePermission):
    """
    Only allows users with role='AUTHOR' to create/edit.

    WHY?
    - Students shouldn't be able to create courses
    - Prevents accidental course creation
    - Enforces business logic

    Used on: CourseViewSet, LessonViewSet, BlockViewSet
    """

    message = "Only authors can create and manage courses."

    def has_permission(self, request, view):
        """
        Check if user has 'AUTHOR' role.

        Called BEFORE the view executes.

        Returns:
        - True: User can proceed
        - False: User gets 403 Forbidden
        """
        # Allow read operations (GET, HEAD, OPTIONS) for everyone
        if request.method in permissions.SAFE_METHODS:
            return True

        # For write operations (POST, PUT, PATCH, DELETE):
        # User must be authenticated AND be an author
        return (
                request.user and
                request.user.is_authenticated and
                request.user.role == 'AUTHOR'
        )


# =============================================================================
# OWNER PERMISSION (Can only edit own courses)
# =============================================================================

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Authors can only edit/delete THEIR OWN courses.
    Everyone can read (if published).

    WHY?
    - John shouldn't be able to edit Sarah's courses
    - Prevents data corruption
    - Security!

    Example:
    - John creates "Python Basics" → John can edit it ✅
    - Sarah tries to edit "Python Basics" → 403 Forbidden ❌
    - Anyone can VIEW published courses ✅
    """

    message = "You can only edit your own courses."

    def has_object_permission(self, request, view, obj):
        """
        Check if user owns this specific object.

        Called AFTER the view retrieves the object.

        Args:
            obj: The Course/Lesson/Block being accessed

        Returns:
            True: User can proceed
            False: User gets 403 Forbidden
        """
        # Read permissions for safe methods (GET, HEAD, OPTIONS)
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions (PUT, PATCH, DELETE):
        # Check if obj belongs to the requesting user

        # For Course objects
        if hasattr(obj, 'author'):
            return obj.author == request.user

        # For Lesson objects (check via course)
        if hasattr(obj, 'course'):
            return obj.course.author == request.user

        # For Block objects (check via lesson.course)
        if hasattr(obj, 'lesson'):
            return obj.lesson.course.author == request.user

        # Default: deny access
        return False


# =============================================================================
# STUDENT ENROLLMENT PERMISSION
# =============================================================================

class IsEnrolledStudent(permissions.BasePermission):
    """
    Students can only view courses they're enrolled in.
    Authors can view their own courses.

    WHY?
    - Private courses should require enrollment
    - Prevents unauthorized access
    - Can add payment later (must enroll = must pay)

    Example:
    - Alice enrolled in "Python Basics" → Can view ✅
    - Bob NOT enrolled in "Python Basics" → 403 Forbidden ❌
    - John (author) can view his own course ✅
    """

    message = "You must be enrolled in this course to view it."

    def has_object_permission(self, request, view, obj):
        """
        Check if user is enrolled or is the course author.
        """
        # Authors can always view their own courses
        if hasattr(obj, 'author') and obj.author == request.user:
            return True

        # For Course objects
        if hasattr(obj, 'enrollments'):
            return obj.enrollments.filter(student=request.user).exists()

        # For Lesson objects (check course enrollment)
        if hasattr(obj, 'course'):
            return obj.course.enrollments.filter(student=request.user).exists()

        # For Block objects (check lesson.course enrollment)
        if hasattr(obj, 'lesson'):
            return obj.lesson.course.enrollments.filter(student=request.user).exists()

        return False


# =============================================================================
# PUBLIC READ PERMISSION (For published courses)
# =============================================================================

class IsPublishedOrAuthor(permissions.BasePermission):
    """
    Anyone can view PUBLISHED courses.
    Authors can view their UNPUBLISHED courses.

    WHY?
    - Public courses should be accessible to everyone
    - Draft courses only visible to author
    - Allows course preview before publishing

    Example:
    - "Python Basics" (published) → Everyone can view ✅
    - "Advanced Django" (unpublished) → Only John (author) can view ✅
    """

    message = "This course is not published yet."

    def has_object_permission(self, request, view, obj):
        """
        Check if course is published OR user is the author.
        """
        # If user is the author, allow access
        if hasattr(obj, 'author') and obj.author == request.user:
            return True

        # For Course objects
        if hasattr(obj, 'is_published'):
            return obj.is_published

        # For Lesson/Block objects (check course)
        if hasattr(obj, 'course'):
            return obj.course.is_published

        if hasattr(obj, 'lesson'):
            return obj.lesson.course.is_published

        return False