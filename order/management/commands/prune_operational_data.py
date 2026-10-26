from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from payments.models import Payment, WebhookEvent
from users.models import RateLimitBucket


class Command(BaseCommand):
    help = "Remove expired throttle buckets and old authenticated webhook payloads"
    def add_arguments(self, parser):
        parser.add_argument("--webhook-days", type=int, default=30)
    def handle(self, *args, **options):
        if options["webhook_days"] < 7:
            raise CommandError("Keep at least 7 days for payment reconciliation.")
        now = timezone.now()
        buckets, _ = RateLimitBucket.objects.filter(expires_at__lt=now).delete()
        # Preserve events while an old checkout still needs identity reconciliation.
        if Payment.objects.filter(paymob_order_id="").exclude(client_secret="").exists():
            events = 0
        else:
            events, _ = WebhookEvent.objects.filter(created_at__lt=now - timedelta(days=options["webhook_days"])).delete()
        self.stdout.write(f"Removed {buckets} expired buckets and {events} webhook events.")
