import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from order.models import Order
from payments.models import Payment, WebhookEvent
from payments.services import apply_transaction_result


class Command(BaseCommand):
    help = "Bind a payment to an independently verified Paymob order ID and replay authenticated callbacks"

    def add_arguments(self, parser):
        parser.add_argument("payment_id", type=int)
        parser.add_argument("provider_order_id")

    @transaction.atomic
    def handle(self, *args, **options):
        provider_id = options["provider_order_id"]
        if not re.fullmatch(r"[1-9][0-9]{0,49}", provider_id):
            raise CommandError("Provide the numeric order ID verified in Paymob, not the merchant reference.")

        try:
            candidate = Payment.objects.get(pk=options["payment_id"])
        except Payment.DoesNotExist as exc:
            raise CommandError("Payment does not exist.") from exc

        # Use the same lock order as initiation, callbacks and expiry.
        Order.objects.select_for_update().get(pk=candidate.order_id)
        payment = Payment.objects.select_for_update().get(pk=candidate.pk)
        if payment.paymob_order_id and payment.paymob_order_id != provider_id:
            raise CommandError("Payment already has a different provider order ID; it was not changed.")
        if Payment.objects.filter(paymob_order_id=provider_id).exclude(pk=payment.pk).exists():
            raise CommandError("Provider order ID is already assigned to another payment.")

        payment.paymob_order_id = provider_id
        payment.save(update_fields=["paymob_order_id"])

        # The operator supplies the verified identity. An unsigned merchant
        # reference alone must never bind a callback to a local payment.
        replayed = 0
        events = WebhookEvent.objects.filter(hmac_valid=True).order_by("created_at", "pk")
        for event in events.iterator():
            payload = event.payload
            if not isinstance(payload, dict) or payload.get("type") != "TRANSACTION":
                continue
            obj = payload.get("obj")
            if not isinstance(obj, dict) or not isinstance(obj.get("order"), dict):
                continue
            if str(obj["order"].get("id", "")) != provider_id:
                continue
            apply_transaction_result(obj)
            replayed += 1

        payment.refresh_from_db()
        self.stdout.write(f"Reconciled payment {payment.pk}; replayed {replayed} authenticated event(s); status: {payment.status}.")
