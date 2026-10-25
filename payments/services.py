import logging

from django.db import transaction

from order.models import Order
from .models import Payment

logger = logging.getLogger(__name__)


def as_bool(value):
    return value is True or str(value).lower() == "true"


def flag(payment, text):
    payment.needs_attention = True
    payment.note = f"{payment.note}\n{text}".strip()
    payment.save(update_fields=["needs_attention", "note"])


@transaction.atomic
def apply_transaction_result(obj):
    reference = str((obj.get("order") or {}).get("merchant_order_id") or "")
    if not reference.startswith("pay-") or not reference[4:].isdigit():
        logger.warning("Callback with unknown reference: %s", reference)
        return

    payment = Payment.objects.filter(pk=int(reference[4:])).first()
    if payment is None:
        logger.warning("Callback for missing payment: %s", reference)
        return

    # Always lock the ORDER first, then the PAYMENT. Every piece of code that
    # touches both must use this same order, so two jobs can never deadlock.
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)

    # Refunds are handled by us later; for now just flag them
    if as_bool(obj.get("is_refunded")) or as_bool(obj.get("has_parent_transaction")):
        flag(payment, "Refund event received, review manually.")
        return

    if as_bool(obj.get("pending")):
        return

    if not as_bool(obj.get("success")):
        if payment.status == Payment.PENDING:
            data = obj.get("data")
            message = data.get("message", "") if isinstance(data, dict) else ""
            payment.status = Payment.FAILED
            payment.note = str(message)
            payment.save(update_fields=["status", "note"])
        return

    # ---- success ----
    if payment.status == Payment.SUCCEEDED:
        return  # duplicate callback, nothing to do

    payment.status = Payment.SUCCEEDED
    payment.paymob_transaction_id = str(obj.get("id"))
    payment.save(update_fields=["status", "paymob_transaction_id"])

    if (
        str(obj.get("amount_cents")) != str(payment.amount_cents)
        or obj.get("currency") != payment.currency
    ):
        flag(payment, "Amount or currency mismatch. Order NOT marked paid.")
    elif order.status == Order.PENDING:
        order.status = Order.PAID
        order.save(update_fields=["status"])
    elif order.status == Order.PAID:
        flag(payment, "Duplicate payment: order was already paid. Refund needed.")
    else:
        flag(payment, f"Paid while order was {order.status}. Decide: fulfill or refund.")