"""
Email settings from the environment, the startup checks (missing settings, SMTP
port/encryption), the api.* logging config, DRF_NUM_PROXIES and the
`send_test_email` / `check_duplicate_emails` commands. No real SMTP server is
contacted.

    python manage.py test api.test_email_settings -v 2
"""

import os
import smtplib
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.checks import run_checks
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from backend.email_config import smtp_port_problem

# Every variable these tests set; the rest are blanked, so the developer's .env
# (loaded with setdefault) can't fill them in.
STARTUP_VARS = ('SECRET_KEY', 'DEBUG', 'EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD',
                'EMAIL_USE_TLS', 'EMAIL_USE_SSL', 'DEFAULT_FROM_EMAIL', 'SITE_URL', 'DRF_NUM_PROXIES')


SMTP = dict(EMAIL_HOST='smtp.example.com', EMAIL_PORT='465', EMAIL_USE_SSL='True', EMAIL_USE_TLS='False',
            EMAIL_HOST_USER='noreply@example.com', EMAIL_HOST_PASSWORD='secret-password',
            DEFAULT_FROM_EMAIL='noreply@example.com', SITE_URL='https://example.com/')


def run_django(code, args=None, **env):
    """Run `code` after django.setup() (or manage.py `args`) in a fresh process,
    DEBUG off, with working email settings unless `env` overrides them."""
    clean = {k: v for k, v in os.environ.items() if k not in STARTUP_VARS}
    clean.update({name: '' for name in STARTUP_VARS})
    clean.update({'DEBUG': 'False', 'SECRET_KEY': 'set-for-this-test', **SMTP, **env},
                 DJANGO_SETTINGS_MODULE='backend.settings')
    command = [sys.executable, 'manage.py', *args] if args else \
        [sys.executable, '-c', 'import django; django.setup()\n' + code]
    return subprocess.run(command, cwd=settings.BASE_DIR, env=clean,
                          capture_output=True, text=True, encoding='utf-8', timeout=60)


class SmtpPortProblemTests(SimpleTestCase):
    def test_matching_pairs_are_fine(self):
        self.assertEqual(smtp_port_problem(465, False, True), '')
        self.assertEqual(smtp_port_problem(587, True, False), '')

    def test_465_needs_ssl_only(self):
        for tls, ssl in [(False, False), (True, False)]:
            self.assertIn('EMAIL_PORT=465 needs EMAIL_USE_TLS=False and EMAIL_USE_SSL=True',
                          smtp_port_problem(465, tls, ssl))

    def test_587_needs_tls_only(self):
        for tls, ssl in [(False, False), (False, True)]:
            self.assertIn('EMAIL_PORT=587 needs EMAIL_USE_TLS=True and EMAIL_USE_SSL=False',
                          smtp_port_problem(587, tls, ssl))

    def test_both_on_is_always_wrong(self):
        for port in (25, 465, 587):
            self.assertIn('both on', smtp_port_problem(port, True, True))

    def test_other_ports_are_not_checked(self):
        self.assertEqual(smtp_port_problem(25, False, False), '')
        self.assertEqual(smtp_port_problem(2525, True, False), '')


def w001():
    return [m for m in run_checks() if m.id == 'api.W001']


class SmtpPortCheckTests(SimpleTestCase):
    """With DEBUG on (local development) a port mismatch is a system check warning;
    without DEBUG the server refuses to start (StartupCheckTests)."""

    @override_settings(EMAIL_HOST='smtp.example.com', EMAIL_PORT=465, EMAIL_USE_TLS=True, EMAIL_USE_SSL=False)
    def test_mismatch_is_a_warning(self):
        messages = w001()
        self.assertEqual(len(messages), 1)
        self.assertFalse(messages[0].is_serious())
        self.assertIn('EMAIL_PORT=465', messages[0].msg)

    @override_settings(EMAIL_HOST='smtp.example.com', EMAIL_PORT=465, EMAIL_USE_TLS=False, EMAIL_USE_SSL=True)
    def test_matching_settings_give_no_warning(self):
        self.assertEqual(w001(), [])

    @override_settings(EMAIL_HOST='', EMAIL_PORT=465, EMAIL_USE_TLS=False, EMAIL_USE_SSL=False)
    def test_not_checked_without_smtp(self):
        self.assertEqual(w001(), [])

    def test_with_debug_on_a_mismatch_is_a_warning_in_check(self):
        result = run_django('', args=['check'], DEBUG='True', EMAIL_PORT='587')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('api.W001', result.stderr)


class StartupCheckTests(SimpleTestCase):
    """Without DEBUG the server refuses to start with incomplete or inconsistent
    email settings (like SECRET_KEY, see api/test_runner.py)."""

    def assert_refuses(self, result, *texts):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('ImproperlyConfigured', result.stderr)
        for text in texts:
            self.assertIn(text, result.stderr)

    def test_starts_with_complete_settings(self):
        result = run_django('print("started")')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'started')

    def test_refuses_without_email_settings(self):
        self.assert_refuses(run_django('', EMAIL_HOST='', DEFAULT_FROM_EMAIL='', SITE_URL=''),
                            'EMAIL_HOST, DEFAULT_FROM_EMAIL, SITE_URL not set.')
        for name in ('EMAIL_HOST', 'DEFAULT_FROM_EMAIL', 'SITE_URL'):
            with self.subTest(name=name):
                self.assert_refuses(run_django('', **{name: ''}), f'{name} not set.')

    def test_refuses_a_port_mismatch(self):
        for env in [dict(EMAIL_PORT='465', EMAIL_USE_SSL='False', EMAIL_USE_TLS='True'),
                    dict(EMAIL_PORT='587', EMAIL_USE_SSL='True', EMAIL_USE_TLS='False'),
                    dict(EMAIL_PORT='587', EMAIL_USE_SSL='False', EMAIL_USE_TLS='False')]:
            with self.subTest(**env):
                self.assert_refuses(run_django('', **env), f"EMAIL_PORT={env['EMAIL_PORT']} needs")

    def test_refuses_tls_and_ssl_together(self):
        self.assert_refuses(run_django('', EMAIL_PORT='2525', EMAIL_USE_SSL='True', EMAIL_USE_TLS='True'),
                            'EMAIL_USE_TLS and EMAIL_USE_SSL are both on')

    def test_starts_with_587_and_tls(self):
        result = run_django('print("started")', EMAIL_PORT='587', EMAIL_USE_SSL='False', EMAIL_USE_TLS='True')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_migrate_refuses_too(self):
        # The container runs `manage.py migrate` first: it must stop, not migrate.
        self.assert_refuses(run_django('', args=['migrate', '--check'], EMAIL_HOST=''), 'EMAIL_HOST not set.')

    def test_debug_without_email_settings_prints_emails_to_the_console(self):
        result = run_django('from django.conf import settings; print(settings.EMAIL_BACKEND, settings.SITE_URL)',
                            DEBUG='True', EMAIL_HOST='', DEFAULT_FROM_EMAIL='', SITE_URL='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ['api.mail_backends.ReadableConsoleEmailBackend',
                                                 'http://127.0.0.1:8000'])


class EmailSettingsFromEnvironmentTests(SimpleTestCase):
    def test_smtp_settings_come_from_the_environment(self):
        result = run_django(
            'from django.conf import settings as s\n'
            'print(s.EMAIL_BACKEND, s.EMAIL_HOST, s.EMAIL_PORT, s.EMAIL_USE_SSL, s.EMAIL_USE_TLS,'
            ' s.EMAIL_HOST_USER, s.DEFAULT_FROM_EMAIL, s.SITE_URL)')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), [
            'django.core.mail.backends.smtp.EmailBackend', 'smtp.example.com', '465', 'True', 'False',
            'noreply@example.com', 'noreply@example.com', 'https://example.com'])

    def test_no_email_secrets_in_the_settings_file(self):
        source = (Path(settings.BASE_DIR) / 'backend' / 'settings.py').read_text(encoding='utf-8')
        self.assertNotIn('smtp.yandex.ru', source)
        self.assertNotRegex(source, r"EMAIL_HOST_PASSWORD\s*=\s*['\"]")


class NumProxiesTests(SimpleTestCase):
    code = 'from django.conf import settings; print(settings.REST_FRAMEWORK["NUM_PROXIES"])'

    def test_default_is_zero(self):
        result = run_django(self.code)
        self.assertEqual(result.stdout.strip(), '0', result.stderr)

    def test_from_the_environment(self):
        result = run_django(self.code, DRF_NUM_PROXIES='1')
        self.assertEqual(result.stdout.strip(), '1', result.stderr)


class LoggingConfigTests(SimpleTestCase):
    def test_api_loggers_write_info_and_tracebacks_to_stderr(self):
        result = run_django(
            'import logging\n'
            'log = logging.getLogger("api.email_confirmation")\n'
            'log.debug("not-shown")\n'
            'log.info("info-shown")\n'
            'try:\n'
            '    1 / 0\n'
            'except ZeroDivisionError:\n'
            '    log.exception("send-failed")\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('not-shown', result.stderr)
        self.assertIn('INFO api.email_confirmation: info-shown', result.stderr)
        self.assertIn('ERROR api.email_confirmation: send-failed', result.stderr)
        self.assertIn('Traceback (most recent call last)', result.stderr)
        self.assertIn('ZeroDivisionError', result.stderr)
        self.assertEqual(result.stdout, '')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   EMAIL_HOST='smtp.example.com', EMAIL_HOST_PASSWORD='secret-password',
                   DEFAULT_FROM_EMAIL='УЧЁБУС <noreply@example.com>', SITE_URL='https://example.com')
class SendTestEmailCommandTests(SimpleTestCase):
    def call(self):
        out, err = StringIO(), StringIO()
        call_command('send_test_email', 'student@example.com', stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_sends_one_email_with_the_settings(self):
        out, err = self.call()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['student@example.com'])
        self.assertEqual(mail.outbox[0].from_email, 'УЧЁБУС <noreply@example.com>')
        self.assertIn('https://example.com', mail.outbox[0].body)
        self.assertIn('Sent (1) to student@example.com', out)
        self.assertIn('password=set', out)
        self.assertNotIn('secret-password', out + err)

    def test_smtp_error_is_raised_with_code_and_traceback(self):
        error = smtplib.SMTPAuthenticationError(535, b'5.7.8 Error: authentication failed')
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=error), \
                mock.patch('sys.stderr', new_callable=StringIO) as stderr:
            with self.assertRaisesMessage(CommandError, 'SMTP 535'):
                self.call()
        self.assertIn('SMTPAuthenticationError', stderr.getvalue())

    def test_any_other_error_is_raised_too(self):
        with mock.patch('django.core.mail.EmailMessage.send', side_effect=TimeoutError('timed out')), \
                mock.patch('sys.stderr', new_callable=StringIO):
            with self.assertRaisesMessage(CommandError, 'TimeoutError: timed out'):
                self.call()

    @override_settings(EMAIL_BACKEND='api.mail_backends.ReadableConsoleEmailBackend')
    def test_warns_when_not_smtp(self):
        with mock.patch('sys.stdout', new_callable=StringIO):  # the console backend prints there
            out, err = self.call()
        self.assertIn('not the SMTP backend', err)


BEFORE = [('api', '0019_course_cover_help_text')]
AFTER = [('api', '0020_user_email_verification')]


class CheckDuplicateEmailsTests(TransactionTestCase):
    """`manage.py check_duplicate_emails` runs on the server BEFORE migration 0020,
    so it is tested on a database at 0019 (no email_verified column yet)."""

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        self.old_user = executor.loader.project_state(BEFORE).apps.get_model('api', 'User')
        self.addCleanup(self.migrate_forward)

    def migrate_forward(self):
        self.old_user.objects.all().delete()
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def add(self, username, email, **extra):
        return self.old_user.objects.create(username=username, email=email, **extra)

    def check(self):
        out = StringIO()
        try:
            call_command('check_duplicate_emails', stdout=out)
        except CommandError as exc:
            return out.getvalue(), str(exc)
        return out.getvalue(), None

    def test_clean_database(self):
        self.add('alice', 'alice@example.com')
        self.add('bob', 'bob@example.com')
        out, error = self.check()
        self.assertIsNone(error)
        self.assertIn('Users: 2', out)
        self.assertIn('Duplicate emails (ignoring case): none', out)
        self.assertIn('Users without an email: 0', out)
        self.assertIn('OK: migration 0020_user_email_verification can run.', out)

    def test_lists_duplicates_ignoring_case_and_users_without_email(self):
        first = self.add('alice', 'Alice@Example.com')
        second = self.add('alice2', 'alice@example.COM', role='AUTHOR', is_staff=True)
        self.add('bob', 'bob@example.com')
        nomail = self.add('ghost', '')
        self.add('ghost2', '')  # several empty emails are fine

        out, error = self.check()

        self.assertEqual(error, 'Fix the duplicate emails in the admin before migrating.')
        self.assertIn('Users: 5', out)
        self.assertIn('Duplicate emails (ignoring case): 1', out)
        self.assertIn('  alice@example.com\n', out)
        self.assertIn(f"id={first.pk} 'alice' <Alice@Example.com> (STUDENT,", out)
        self.assertIn(f"id={second.pk} 'alice2' <alice@example.COM> (AUTHOR, staff,", out)
        self.assertNotIn("'bob'", out)
        self.assertIn('Users without an email: 2', out)
        self.assertIn(f"id={nomail.pk} 'ghost' <>", out)
        self.assertNotIn('can run', out)

    def test_migration_stops_on_duplicates_and_names_them(self):
        self.add('alice', 'Alice@Example.com')
        self.add('alice2', 'alice@example.com')
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        with self.assertRaisesMessage(RuntimeError, 'fix them in the admin before migrating: alice@example.com'):
            executor.migrate(AFTER)
