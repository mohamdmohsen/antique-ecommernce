from django.db import transaction
from django.db.models import Exists, OuterRef
from django.db.models.functions import Round

from catalog.models import Product
from payments.models import Payment
from payments.services import flag_for_reconciliation, needs_reconciliation
from .models import Order


def orders_awaiting_shipping():
    """Paid orders with a matching payment and no refund; tracking can be added next."""
    confirmed_payment = Payment.objects.filter(
        order_id=OuterRef("pk"), status=Payment.SUCCEEDED,
        amount_cents=Round(OuterRef("total") * 100),
    )
    return Order.objects.filter(status=Order.PAID).filter(
        Exists(confirmed_payment)
    ).exclude(payments__refund__isnull=False)


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


@transaction.atomic
def transition_order(order_id, status, actor):
    from decimal import Decimal
    from django.core.exceptions import ValidationError
    from .models import OrderStatusEvent

    if not actor.is_active or not actor.is_staff or not actor.has_perm("order.change_order"):
        raise ValidationError("You do not have permission to change fulfillment status.")
    order = Order.objects.select_for_update().get(pk=order_id)
    allowed = {Order.PAID: Order.SHIPPED, Order.SHIPPED: Order.DELIVERED}
    if allowed.get(order.status) != status:
        raise ValidationError("Only paid → shipped → delivered transitions are allowed.")
    if not order.payments.filter(status=Payment.SUCCEEDED, amount_cents=int(order.total * Decimal(100))).exists():
        raise ValidationError("The order needs a confirmed, unrefunded payment before fulfillment.")
    if order.payments.filter(refund__isnull=False).exists():
        raise ValidationError("Resolve the refund before fulfilling this order.")
    if status == Order.SHIPPED and not order.tracking_number.strip():
        raise ValidationError("Enter a tracking number before marking the order shipped.")
    previous = order.status
    order.status = status
    order.save(update_fields=["status"])
    OrderStatusEvent.objects.create(order=order, actor=actor, previous_status=previous, status=status)
    return order
