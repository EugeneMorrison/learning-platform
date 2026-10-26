"""python manage.py check_duplicate_emails: read-only check before migration
0020_user_email_verification, which adds a case-insensitive unique constraint
on User.email and stops on duplicates.

Lists the addresses several accounts share (ignoring case), with their
accounts, and the accounts without an email (they are allowed: not affected by
the constraint, confirmed by the migration, but can't get emails). Exits with
status 1 when there are duplicates: fix them in the admin, then migrate.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.db.models.functions import Lower

from api.models import User


def _describe(user):
    flags = [user.role] + (['staff'] if user.is_staff else []) + ([] if user.is_active else ['inactive'])
    return f'id={user.pk} {user.username!r} <{user.email}> ({", ".join(flags)}, joined {user.date_joined:%Y-%m-%d})'


class Command(BaseCommand):
    help = 'List case-insensitive duplicate emails and users without an email (read-only).'

    def handle(self, **options):
        users = User.objects.only('id', 'username', 'email', 'role', 'is_staff', 'is_active', 'date_joined')
        duplicates = list(
            users.exclude(email='').annotate(address=Lower('email')).values('address')
            .annotate(n=Count('id')).filter(n__gt=1).order_by('address').values_list('address', flat=True)
        )
        empty = list(users.filter(email='').order_by('id'))

        self.stdout.write(f'Users: {users.count()}')
        if duplicates:
            self.stdout.write(self.style.ERROR(f'Duplicate emails (ignoring case): {len(duplicates)}'))
            for address in duplicates:
                self.stdout.write(f'  {address}')
                for user in users.annotate(address=Lower('email')).filter(address=address).order_by('id'):
                    self.stdout.write(f'    {_describe(user)}')
        else:
            self.stdout.write(self.style.SUCCESS('Duplicate emails (ignoring case): none'))

        self.stdout.write(f'Users without an email: {len(empty)}')
        for user in empty:
            self.stdout.write(f'  {_describe(user)}')

        if duplicates:
            raise CommandError('Fix the duplicate emails in the admin before migrating.')
        self.stdout.write(self.style.SUCCESS('OK: migration 0020_user_email_verification can run.'))
