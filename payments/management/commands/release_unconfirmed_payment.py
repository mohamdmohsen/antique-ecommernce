from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from order.models import Order
from payments.models import Payment
from payments.services import needs_reconciliation


class Command(BaseCommand):
    help = (
        "Let a customer pay again when a payment attempt is stuck as 'needs review' and "
        "Paymob never created a checkout for it (for example the request was rejected)."
    )

    def add_arguments(self, parser):
        parser.add_argument("payment_id", type=int)
        parser.add_argument(
            "--confirmed-not-created", action="store_true",
            help="I searched the Paymob dashboard for reference pay-<ID> and found NO order or transaction.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirmed_not_created"]:
            raise CommandError(
                "Open the Paymob dashboard and search for the reference pay-%d. If there is no "
                "order or transaction, run this again with --confirmed-not-created. If there IS "
                "one, use reconcile_payment instead." % options["payment_id"]
            )
        try:
            candidate = Payment.objects.get(pk=options["payment_id"])
        except Payment.DoesNotExist as exc:
            raise CommandError("Payment does not exist.") from exc

        # Same lock order as initiation, callbacks and expiry: order first, then payment.
        Order.objects.select_for_update().get(pk=candidate.order_id)
        payment = Payment.objects.select_for_update().get(pk=candidate.pk)

        if payment.client_secret or payment.paymob_order_id or payment.paymob_transaction_id or payment.succeeded_at:
            raise CommandError("Paymob already knows this payment (it has a provider ID or secret). "
                               "It was not changed. Use reconcile_payment with the verified Paymob order ID.")
        if not needs_reconciliation(payment):
            raise CommandError("This payment is not waiting for review; nothing to release.")

        payment.status = Payment.FAILED
        payment.intention_state = Payment.NEW
        payment.needs_attention = False
        payment.note = f"{payment.note}\nReleased by an operator: confirmed in Paymob that no checkout exists.".strip()
        payment.save(update_fields=["status", "intention_state", "needs_attention", "note"])
        self.stdout.write(f"Payment {payment.pk} released. Order {payment.order_id} can be paid again.")
