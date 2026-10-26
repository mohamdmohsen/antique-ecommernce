from django.db import transaction

from catalog.models import Product
from payments.models import Payment
from .models import Order


@transaction.atomic
def cancel_if_unpaid(order_id):
    # Lock order first, then payments, then products (same order as the webhook)
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status != Order.PENDING:
        return False  # changed while we were waiting, leave it alone

    payments = list(order.payments.select_for_update())
    if any(p.status == Payment.SUCCEEDED for p in payments):
        return False  # money was taken, a person must decide

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