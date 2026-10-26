"""python manage.py send_test_email <address>: send one email with the real
settings, never silently; on failure print the SMTP reply and the traceback."""

import smtplib
import traceback

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Send one test email with the current EMAIL_* settings and report any SMTP error.'

    def add_arguments(self, parser):
        parser.add_argument('address')

    def handle(self, address, **options):
        s = settings
        self.stdout.write(
            f'EMAIL_BACKEND={s.EMAIL_BACKEND}\n'
            f'EMAIL_HOST={s.EMAIL_HOST!r} EMAIL_PORT={s.EMAIL_PORT}\n'
            f'EMAIL_USE_SSL={s.EMAIL_USE_SSL} EMAIL_USE_TLS={s.EMAIL_USE_TLS} '
            f'EMAIL_TIMEOUT={getattr(s, "EMAIL_TIMEOUT", None)}\n'
            f'EMAIL_HOST_USER={s.EMAIL_HOST_USER!r} '
            f'password={"set" if s.EMAIL_HOST_PASSWORD else "EMPTY"}\n'
            f'DEFAULT_FROM_EMAIL={s.DEFAULT_FROM_EMAIL!r} SITE_URL={s.SITE_URL!r}'
        )
        if 'smtp' not in s.EMAIL_BACKEND:
            self.stderr.write('Warning: not the SMTP backend, nothing leaves this machine.')
        message = EmailMessage(
            'УЧЁБУС: тестовое письмо',
            f'Если вы читаете это письмо, отправка почты с {s.SITE_URL} работает.',
            s.DEFAULT_FROM_EMAIL, [address],
            connection=get_connection(fail_silently=False),
        )
        try:
            sent = message.send()
        except smtplib.SMTPResponseException as exc:
            traceback.print_exc()
            raise CommandError(f'SMTP {exc.smtp_code}: {exc.smtp_error!r}')
        except smtplib.SMTPRecipientsRefused as exc:
            traceback.print_exc()
            raise CommandError(f'Recipients refused: {exc.recipients!r}')
        except Exception as exc:
            traceback.print_exc()
            raise CommandError(f'{type(exc).__name__}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Sent ({sent}) to {address}. Check inbox and spam.'))
