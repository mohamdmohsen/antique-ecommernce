import sentry_sdk
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send one test error to GlitchTip to check that reporting works"

    def handle(self, *args, **options):
        if not settings.GLITCHTIP_DSN:
            raise CommandError("GLITCHTIP_DSN is empty. Put your project DSN in .env first.")
        if not sentry_sdk.get_client().is_active():
            raise CommandError("GlitchTip did not start. Check that GLITCHTIP_DSN is copied correctly.")

        try:
            raise RuntimeError("GlitchTip test error from 'manage.py glitchtip_test' (safe to ignore)")
        except RuntimeError:
            event_id = sentry_sdk.capture_exception()

        sentry_sdk.flush(timeout=10)  # wait until the report has really been sent
        self.stdout.write(self.style.SUCCESS(
            f"Test error sent (event {event_id}, environment {settings.GLITCHTIP_ENVIRONMENT}). "
            "It should appear in your GlitchTip Issues page within a few seconds."
        ))
