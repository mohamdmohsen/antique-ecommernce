from django.db import transaction

from catalog.models import Product
from payments.models import Payment
from payments.services import flag_for_reconciliation, needs_reconciliation
from .models import Order


@transaction.atomic
def cancel_if_unpaid(order_id):
    """Cancel one unpaid order and give its stock back, exactly once.

    Lock order: ORDER first, then payments, then products. The payment
    webhook locks in the same order, so the two can never deadlock.
    """
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status != Order.PENDING:
        return False  # changed while we waited (for example paid), leave it alone

    payments = list(order.payments.select_for_update())
    if any(p.status == Payment.SUCCEEDED for p in payments):
        return False  # money was taken: a person decides, never cancel silently

    unresolved = [p for p in payments if needs_reconciliation(p)]
    if unresolved:
        for payment in unresolved:
            flag_for_reconciliation(payment)
        return False  # an old checkout may have taken money; keep stock reserved

    for item in order.items.order_by("product_id"):
        product = Product.objects.select_for_update().get(pk=item.product_id)
        product.stock += item.quantity
        product.save(update_fields=["stock"])

    for payment in payments:
        if payment.status == Payment.PENDING:
            payment.status = Payment.FAILED
            payment.note = "Order expired"
            payment.save(update_fields=["status", "note"])

    order.status = Order.CANCELLED
    order.save(update_fields=["status"])
    return True
