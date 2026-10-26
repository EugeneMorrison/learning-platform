from django.contrib import admin
from django.utils.functional import lazy

from .models import AuthorProfile, Block, Course, Enrollment, Lesson, Progress, Review, User
from .templatetags.public_site import get_brand_name

# Admin header and browser-tab title: the site name (settings.BRAND_NAMES), in
# the language of each request.
admin.site.site_header = lazy(get_brand_name, str)()
admin.site.site_title = lazy(get_brand_name, str)()


# =============================================================================
# USER ADMIN
# =============================================================================

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'role', 'email_verified', 'is_staff', 'date_joined']
    list_filter = ['role', 'email_verified', 'is_staff', 'is_active']
    search_fields = ['username', 'email']
    ordering = ['-date_joined']
    # The sign-up acceptances (personal data consent; user agreement) are shown, never edited.
    readonly_fields = ['accepted_privacy_at', 'privacy_version', 'accepted_terms_at', 'terms_version']

    def get_changeform_initial_data(self, request):
        """Users added here are confirmed from the start (the box stays editable);
        only public sign-up creates accounts that wait for the emailed link."""
        return {'email_verified': True, **super().get_changeform_initial_data(request)}


# =============================================================================
# COURSE ADMIN
# =============================================================================

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'tag', 'level', 'price', 'old_price', 'sort_order', 'is_published', 'created_at']
    list_editable = ['price', 'sort_order']  # tweak pricing/order straight from the list
    list_filter = ['is_published', 'level', 'created_at']
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

# =============================================================================
# LANDING PAGE CONTENT
# =============================================================================

@admin.register(AuthorProfile)
class AuthorProfileAdmin(admin.ModelAdmin):
    """Single author profile: adding is disabled once one exists. The public pages
    don't show the photo at the moment ("Обо мне", /about/, uses the hero's cut-out).
    The bio lives in that page's template, so bio_ru / bio_en stay in the database
    but are left out of the form."""
    list_display = ['name', 'name_en', 'stepik_url']
    # name_en right after name in the edit form.
    fields = ['name', 'name_en', 'photo', 'stepik_url']

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not AuthorProfile.objects.exists()


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['student_name', 'course', 'source', 'is_published', 'order']
    list_editable = ['is_published', 'order']
    list_filter = ['is_published', 'source', 'course']
    search_fields = ['student_name', 'text_ru', 'text_en']
    ordering = ['order', 'id']
