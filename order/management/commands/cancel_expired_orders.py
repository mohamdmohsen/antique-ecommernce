from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from order.models import Order
from order.services import cancel_if_unpaid


class Command(BaseCommand):
    help = "Cancel unpaid orders past the payment window and return their stock"

    def handle(self, *args, **options):
        minutes = settings.ORDER_PAYMENT_WINDOW_MINUTES + settings.ORDER_CANCEL_GRACE_MINUTES
        cutoff = timezone.now() - timedelta(minutes=minutes)

        ids = list(
            Order.objects.filter(status=Order.PENDING, created_at__lt=cutoff)
            .values_list("id", flat=True)
        )
        cancelled = sum(1 for order_id in ids if cancel_if_unpaid(order_id))
        self.stdout.write(f"Cancelled {cancelled} order(s)")
