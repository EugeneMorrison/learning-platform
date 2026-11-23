def can_export_any_course(user):
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_superuser or (user.is_staff and user.has_perm('api.export_any_course'))))


def can_export(user, course):
    return bool(user and user.is_authenticated and user.is_active and (
        (user.pk == course.author_id and user.role in ('AUTHOR', 'ADMIN')) or can_export_any_course(user)))
