from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from antique import analytics


class Command(BaseCommand):
    help = "Send one test event to PostHog to check that analytics works"

    def handle(self, *args, **options):
        if not analytics.is_enabled():
            raise CommandError("POSTHOG_API_KEY is empty. Put your project API key in .env first.")

        client = analytics.get_client()
        client.capture(
            "posthog_test",
            distinct_id="posthog-test",
            properties={"environment": settings.POSTHOG_ENVIRONMENT},
        )
        client.flush()  # wait until the event has really been sent
        self.stdout.write(self.style.SUCCESS(
            f"Test event sent to {settings.POSTHOG_HOST} (environment {settings.POSTHOG_ENVIRONMENT}). "
            "Look for 'posthog_test' in PostHog > Activity (it can take a minute)."
        ))
