from django.db import transaction

from cart.models import CartItem
from catalog.models import Product
from payments.models import Payment
from payments.services import flag_for_reconciliation, needs_reconciliation
from .models import Order, OrderItem


class CheckoutError(Exception):
    """The cart cannot become an order. `code` is stable, `message` is for the API."""

    def __init__(self, code, message, product_title=""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.product_title = product_title


def create_order_from_cart(user, shipping):
    """Turn the user's cart into an order, or change nothing at all.

    Everything happens in one transaction: if any item is out of stock the order,
    the stock changes and the cart are all left exactly as they were.
    """
    with transaction.atomic():
        cart_items = list(
            CartItem.objects.select_for_update().filter(user=user).order_by("product_id")
        )

        if not cart_items:
            raise CheckoutError("empty", "Cart is empty")

        order = Order.objects.create(user=user, total=0, **shipping)

        total = 0
        for item in cart_items:
            product = Product.objects.select_for_update().get(pk=item.product_id)

            if item.quantity > product.stock:
                raise CheckoutError(
                    "stock", f"Not enough stock for {product.title}", product.title
                )

            product.stock -= item.quantity
            product.save(update_fields=["stock"])

            OrderItem.objects.create(
                order=order,
                product=product,
                title=product.title,
                price=product.price,
                quantity=item.quantity,
            )
            total += product.price * item.quantity

        order.total = total
        order.save(update_fields=["total"])

        CartItem.objects.filter(user=user, pk__in=[item.pk for item in cart_items]).delete()

    return order


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
