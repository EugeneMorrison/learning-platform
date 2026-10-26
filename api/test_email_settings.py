"""
Email settings from the environment, the SMTP port/encryption check, the api.*
logging config, DRF_NUM_PROXIES and `manage.py send_test_email`. No real SMTP
server is contacted.

    python manage.py test api.test_email_settings -v 2
"""

import os
import smtplib
import subprocess
import sys
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.checks import run_checks
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from backend.email_config import smtp_port_problem

# Every variable these tests set; the rest are blanked, so the developer's .env
# (loaded with setdefault) can't fill them in.
STARTUP_VARS = ('SECRET_KEY', 'DEBUG', 'EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD',
                'EMAIL_USE_TLS', 'EMAIL_USE_SSL', 'DEFAULT_FROM_EMAIL', 'SITE_URL', 'DRF_NUM_PROXIES')


def run_django(code, args=None, **env):
    """Run `code` after django.setup() (or manage.py `args`) in a fresh process."""
    clean = {k: v for k, v in os.environ.items() if k not in STARTUP_VARS}
    clean.update({name: '' for name in STARTUP_VARS})
    clean.update({'DEBUG': 'False', 'SECRET_KEY': 'set-for-this-test'}, **env,
                 DJANGO_SETTINGS_MODULE='backend.settings')
    command = [sys.executable, 'manage.py', *args] if args else \
        [sys.executable, '-c', 'import django; django.setup()\n' + code]
    return subprocess.run(command, cwd=settings.BASE_DIR, env=clean,
                          capture_output=True, text=True, encoding='utf-8', timeout=60)


SMTP = dict(EMAIL_HOST='smtp.example.com', EMAIL_HOST_USER='noreply@example.com',
            EMAIL_HOST_PASSWORD='secret-password', DEFAULT_FROM_EMAIL='noreply@example.com',
            SITE_URL='https://example.com/')


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
    """A warning for now (step 1): the server still starts."""

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

    def test_server_starts_with_a_mismatch_and_check_warns(self):
        result = run_django('', args=['check'], **SMTP, EMAIL_PORT='587', EMAIL_USE_SSL='True')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('api.W001', result.stderr)


class EmailSettingsFromEnvironmentTests(SimpleTestCase):
    def test_smtp_settings_come_from_the_environment(self):
        result = run_django(
            'from django.conf import settings as s\n'
            'print(s.EMAIL_BACKEND, s.EMAIL_HOST, s.EMAIL_PORT, s.EMAIL_USE_SSL, s.EMAIL_USE_TLS,'
            ' s.EMAIL_HOST_USER, s.DEFAULT_FROM_EMAIL, s.SITE_URL)',
            **SMTP, EMAIL_PORT='465', EMAIL_USE_SSL='True', EMAIL_USE_TLS='False')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), [
            'django.core.mail.backends.smtp.EmailBackend', 'smtp.example.com', '465', 'True', 'False',
            'noreply@example.com', 'noreply@example.com', 'https://example.com'])

    def test_without_email_host_emails_go_to_the_console_and_the_server_starts(self):
        # Step 1: no hard startup check yet, even with DEBUG off.
        result = run_django('from django.conf import settings; print(settings.EMAIL_BACKEND)')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ReadableConsoleEmailBackend', result.stdout)


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
