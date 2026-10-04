from django.contrib import admin
from .models import User, Course, Lesson, Block, Enrollment, Progress


# =============================================================================
# USER ADMIN
# =============================================================================

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'role', 'is_staff', 'date_joined']
    list_filter = ['role', 'is_staff', 'is_active']
    search_fields = ['username', 'email']
    ordering = ['-date_joined']


# =============================================================================
# COURSE ADMIN
# =============================================================================

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'price', 'old_price', 'sort_order', 'is_published', 'created_at']
    list_editable = ['price', 'sort_order']  # tweak pricing/order straight from the list
    list_filter = ['is_published', 'created_at']
    search_fields = ['title', 'description']
    ordering = ['sort_order', '-created_at']

    # NOTE: no prepopulated_fields for slug — the admin's JS prepopulate strips
    # non-ASCII, so Cyrillic titles would yield empty slugs. Leaving slug blank
    # lets Course.save() transliterate it server-side instead.
    readonly_fields = ['created_at', 'updated_at']


# =============================================================================
# LESSON ADMIN
# =============================================================================

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'order_index', 'created_at']
    list_filter = ['course', 'created_at']
    search_fields = ['title']
    ordering = ['course', 'order_index']


# =============================================================================
# BLOCK ADMIN
# =============================================================================

@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ['lesson', 'type', 'order_index', 'created_at']
    list_filter = ['type', 'created_at']
    ordering = ['lesson', 'order_index']


# =============================================================================
# ENROLLMENT ADMIN
# =============================================================================

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ['student', 'course', 'enrolled_at']
    list_filter = ['enrolled_at']
    search_fields = ['student__username', 'course__title']
    ordering = ['-enrolled_at']


# =============================================================================
# PROGRESS ADMIN
# =============================================================================

@admin.register(Progress)
class ProgressAdmin(admin.ModelAdmin):
    list_display = ['student', 'lesson', 'block', 'completed', 'is_correct', 'completed_at']
    list_filter = ['completed', 'is_correct', 'created_at']
    search_fields = ['student__username', 'lesson__title']
    ordering = ['-updated_at']