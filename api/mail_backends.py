"""Email backend for local development (settings: DEBUG on, no EMAIL_HOST)."""

from django.core.mail.backends.console import EmailBackend as ConsoleEmailBackend


class ReadableConsoleEmailBackend(ConsoleEmailBackend):
    """Like Django's console backend, but prints the plain-text body as text.
    Django's own one prints the MIME message, where a Cyrillic body is base64,
    so a confirmation link could not be copied from the terminal."""

    def write_message(self, message):
        self.stream.write(
            f'From: {message.from_email}\n'
            f'To: {", ".join(message.to)}\n'
            f'Subject: {message.subject}\n\n'
            f'{message.body}\n'
            f'{"-" * 79}\n'
        )
