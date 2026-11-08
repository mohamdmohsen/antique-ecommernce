import logging
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.db import transaction
from django.core.mail import mail_admins
from django.utils import timezone
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

from antique.analytics import track
from order.models import Order
from .models import Payment, Refund
from .paymob import create_intention

logger = logging.getLogger(__name__)

RECONCILIATION_NOTE = "Existing checkout has no verified Paymob order ID; reconcile before retrying or releasing stock."


def needs_reconciliation(payment):
    return (payment.intention_state in {Payment.CREATING, Payment.UNKNOWN}
            or bool(payment.client_secret and not payment.paymob_order_id))


def flag_for_reconciliation(payment):
    if RECONCILIATION_NOTE not in payment.note:
        flag(payment, RECONCILIATION_NOTE)
    elif not payment.needs_attention:
        payment.needs_attention = True
        payment.save(update_fields=["needs_attention"])


def as_bool(value):
    return value is True or str(value).lower() == "true"


def flag(payment, text):
    newly_flagged = not payment.needs_attention
    payment.needs_attention = True
    payment.note = f"{payment.note}\n{text}".strip()
    payment.save(update_fields=["needs_attention", "note"])
    if newly_flagged:
        def notify():
            try:
                mail_admins("Payment needs attention", f"Review payment {payment.pk} in the shop admin.")
            except Exception:
                logger.exception("Payment attention email delivery failed")
        transaction.on_commit(notify)


@transaction.atomic
def apply_transaction_result(obj):
    # Find the payment by Paymob's order id. It is inside the signed HMAC fields
    # (order.id), so nobody can point a valid signature at a different payment.
    paymob_order_id = str((obj.get("order") or {}).get("id") or "")
    payment = (
        Payment.objects.filter(paymob_order_id=paymob_order_id).first()
        if paymob_order_id
        else None
    )
    if payment is None:
        logger.warning("Callback for unknown Paymob order: %s", paymob_order_id)
        return

    # Our own reference is NOT signed, so it is only a second check, never the key
    reference = str((obj.get("order") or {}).get("merchant_order_id") or "")
    if reference != f"pay-{payment.id}":
        logger.warning("Reference mismatch on payment %s: %s", payment.id, reference)
        return

    # Always lock the ORDER first, then the PAYMENT. Every piece of code that
    # touches both must use this same order, so two jobs can never deadlock.
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)

    # Only an identified requested-refund result may change accounting.
    # Parent IDs and cumulative refunded amounts are not signed.
    refund = Refund.objects.filter(payment=payment).first()
    original_refund = (
        as_bool(obj.get("is_refunded"))
        and str(obj.get("id")) == payment.paymob_transaction_id
    )
    requested_refund = refund and refund.provider_id and str(obj.get("id")) == refund.provider_id
    if original_refund and not requested_refund:
        # Paymob signs the original amount, not the cumulative refunded amount.
        # A dashboard partial refund must never be inferred to be a full refund.
        if not refund:
            refund = Refund.objects.create(payment=payment, amount_cents=payment.amount_cents, status=Refund.UNKNOWN,
                                          note="Dashboard refund observed; independently verify the refunded amount before reconciliation.")
        if refund.status != Refund.SUCCEEDED:
            flag(payment, "Dashboard refund observed; verify amount in Paymob and reconcile the refund ledger.")
        return
    if requested_refund:
        if (as_bool(obj.get("success")) and not as_bool(obj.get("pending"))
                and str(obj.get("amount_cents")) == str(payment.amount_cents)
                and obj.get("currency") == payment.currency):
            payment.status = Payment.REFUNDED
            payment.save(update_fields=["status"])
            refund.status = Refund.SUCCEEDED
            refund.save(update_fields=["status"])
        else:
            flag(payment, "Refund event needs reconciliation before accounting changes.")
        return
    if as_bool(obj.get("is_refunded")) or as_bool(obj.get("has_parent_transaction")):
        flag(payment, "Unmatched refund or child transaction received; review manually.")
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
            track("payment_failed", order.user_id, order_id=order.pk)
        return

    # ---- success ----
    if payment.status in {Payment.SUCCEEDED, Payment.REFUNDED}:
        return  # duplicate callback, nothing to do

    payment.status = Payment.SUCCEEDED
    payment.paymob_transaction_id = str(obj.get("id"))
    if payment.succeeded_at is None:
        payment.succeeded_at = timezone.now()
    payment.save(update_fields=["status", "paymob_transaction_id", "succeeded_at"])

    if (
        str(obj.get("amount_cents")) != str(payment.amount_cents)
        or obj.get("currency") != payment.currency
    ):
        flag(payment, "Amount or currency mismatch. Order NOT marked paid.")
    elif order.status == Order.PENDING:
        order.status = Order.PAID
        order.save(update_fields=["status"])
        track("order_paid", order.user_id, order_id=order.pk, total=order.total, currency=payment.currency)
    elif order.status == Order.PAID:
        flag(payment, "Duplicate payment: order was already paid. Refund needed.")
    else:
        flag(payment, f"Paid while order was {order.status}. Decide: fulfill or refund.")


def request_full_refund(payment_id, actor):
    """Reserve one refund before HTTP. Repeated actions never resend the charge."""
    from django.conf import settings
    from django.core.exceptions import ValidationError
    from .paymob import refund_transaction

    if not actor.is_active or not actor.is_staff or not actor.has_perm("payments.change_payment"):
        raise ValidationError("You do not have permission to issue refunds.")
    if not settings.PAYMOB_API_KEY:
        raise ValidationError("Configure the Paymob refund API key before requesting a refund.")
    with transaction.atomic():
        candidate = Payment.objects.get(pk=payment_id)
        Order.objects.select_for_update().get(pk=candidate.order_id)
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        existing = Refund.objects.filter(payment=payment).first()
        if existing:
            return existing
        if payment.status != Payment.SUCCEEDED or not payment.paymob_transaction_id:
            raise ValidationError("Only a successful payment with a provider transaction ID can be refunded.")
        refund = Refund.objects.create(payment=payment, amount_cents=payment.amount_cents, requested_by=actor)

    try:
        result = refund_transaction(payment)
        provider_id = str(result.get("id") or "")
        matched = str(result.get("amount_cents")) == str(refund.amount_cents)
        succeeded = result.get("success") is True and result.get("pending") is False and matched and provider_id
    except Exception:
        # Do not log response bodies or API credentials. A timeout is ambiguous.
        logger.error("Refund request needs reconciliation for payment %s", payment.pk)
        result = {}
        provider_id = ""
        succeeded = False

    with transaction.atomic():
        Order.objects.select_for_update().get(pk=payment.order_id)
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        # A webhook may already have confirmed the outcome while HTTP was in flight.
        if refund.status != Refund.SUCCEEDED:
            refund.provider_id = provider_id[:50]
            if succeeded:
                refund.status = Refund.SUCCEEDED
                payment.status = Payment.REFUNDED
                payment.save(update_fields=["status"])
            elif result.get("pending") is True and provider_id:
                refund.status = Refund.PENDING
            else:
                refund.status = Refund.UNKNOWN
                refund.note = "Provider result uncertain. Verify it before any further refund attempt."
                flag(payment, "Refund outcome uncertain; reconcile in Paymob. Automatic retry is blocked.")
            refund.save(update_fields=["provider_id", "status", "note"])
    return refund



class PaymentStartError(Exception):
    """The customer cannot pay right now. `code` is stable, `message` is for the API."""

    def __init__(self, code, message, status):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def provider_rejected(exc):
    """True when Paymob CERTAINLY did not create a checkout for this request.

    Then a retry cannot charge the customer twice, so the order must stay payable.
    Anything uncertain (a timeout after the request was sent, a 5xx, a strange 2xx
    answer) returns False and keeps the strict "needs review" protection.
    """
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        return 400 <= code < 500 and code != 408  # request refused: bad key, bad field, wrong integration
    if isinstance(exc, requests.ConnectTimeout):
        return True  # never connected, so nothing was sent
    if isinstance(exc, requests.ConnectionError):
        reason = getattr(exc.args[0], "reason", None) if exc.args else None
        return isinstance(reason, (NewConnectionError, ConnectTimeoutError))  # refused / DNS failure
    return False


def rejection_note(exc):
    """Operator-facing explanation: what Paymob said, so the real cause is visible."""
    response = getattr(exc, "response", None)
    if response is not None:
        body = " ".join(response.text.split())[:300]
        return f"Paymob rejected the checkout request (HTTP {response.status_code}): {body}"
    return (f"Could not reach Paymob ({type(exc).__name__}). Check the server's internet "
            "access and PAYMOB_INTENTION_URL.")


def checkout_url(payment):
    query = urlencode({"publicKey": settings.PAYMOB_PUBLIC_KEY, "clientSecret": payment.client_secret})
    return f"{settings.PAYMOB_CHECKOUT_URL}?{query}"


def start_payment_for_order(order_id, user):
    """Reserve one intention durably, release locks, then call the provider.

    A concurrent click gets409 while initialization is running. Unknown outcomes
    are never retried automatically. Existing identified checkouts are reused.
    """
    with transaction.atomic():
        payment, error = _reserve_intention(order_id, user)
        ready_url = checkout_url(payment) if payment and payment.client_secret else None
    if error:
        raise error
    if ready_url:
        track("payment_started", user.pk, order_id=order_id, reused=True)
        return ready_url

    # No database transaction or row lock spans the outbound HTTP request.
    try:
        secret, provider_id = create_intention(payment)
        provider_id = str(provider_id)
        if (not isinstance(secret, str) or not 1 <= len(secret) <= 255
                or not provider_id.isascii() or not provider_id.isdigit()
                or not 1 <= len(provider_id) <= 50):
            raise ValueError("Incomplete provider identity")
    except Exception as exc:
        if provider_rejected(exc):
            # Paymob refused the request, so no checkout exists. Release this attempt
            # (the order stays payable) and keep the reason where an operator can read it.
            note = rejection_note(exc)
            logger.error("Paymob rejected payment %s: %s", payment.pk, note)
            with transaction.atomic():
                Order.objects.select_for_update().get(pk=payment.order_id)
                current = Payment.objects.select_for_update().get(pk=payment.pk)
                if current.intention_state == Payment.CREATING:
                    current.intention_state = Payment.NEW
                    current.status = Payment.FAILED
                    current.note = f"{current.note}\n{note}".strip()
                    current.save(update_fields=["intention_state", "status", "note"])
            raise PaymentStartError("provider_rejected",
                "The payment provider could not start this payment. Please try again in a few minutes.", 502)
        # Provider may have acted before a timeout or malformed response. Preserve
        # the reservation and stock, alert an operator, and do not send it again.
        logger.exception("Paymob intention outcome uncertain for payment %s", payment.pk)
        with transaction.atomic():
            Order.objects.select_for_update().get(pk=payment.order_id)
            current = Payment.objects.select_for_update().get(pk=payment.pk)
            if current.intention_state == Payment.CREATING:
                current.intention_state = Payment.UNKNOWN
                current.save(update_fields=["intention_state"])
            flag_for_reconciliation(current)
        raise PaymentStartError("needs_review", "Payment initialization needs review before retrying. Please contact support.", 502)

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        current = Payment.objects.select_for_update().get(pk=payment.pk)
        if current.paymob_order_id and current.paymob_order_id != str(provider_id):
            flag(current, "Conflicting provider order identity; independently reconcile before retrying.")
            error = PaymentStartError("needs_review", "Payment identity needs review.", 409)
        else:
            current.client_secret = secret
            current.paymob_order_id = str(provider_id)
            current.intention_state = Payment.READY
            current.save(update_fields=["client_secret", "paymob_order_id", "intention_state"])
            error = None
            if order.status != Order.PENDING:
                error = PaymentStartError("not_payable", "Order cannot be paid", 400)
    if error:
        raise error
    track("payment_started", user.pk, order_id=order_id, reused=False)
    return checkout_url(current)


def _reserve_intention(order_id, user):
    order = Order.objects.select_for_update().filter(pk=order_id, user=user).first()
    if order is None:
        return None, PaymentStartError("not_found", "Order not found", 404)
    if order.status != Order.PENDING:
        return None, PaymentStartError("not_payable", "Order cannot be paid", 400)
    for previous in order.payments.select_for_update().order_by("pk"):
        if previous.intention_state == Payment.CREATING:
            return None, PaymentStartError("busy", "Checkout is being created. Please try again shortly.", 409)
        if needs_reconciliation(previous):
            flag_for_reconciliation(previous)
            return None, PaymentStartError("needs_review", "An existing payment needs review. Please contact support before retrying.", 409)
    deadline = order.created_at + timedelta(minutes=settings.ORDER_PAYMENT_WINDOW_MINUTES)
    if timezone.now() > deadline:
        return None, PaymentStartError("expired", "Order expired", 400)
    payment = Payment.objects.filter(order=order, status=Payment.PENDING).first()
    if payment is None:
        payment = Payment.objects.create(order=order, amount_cents=int(order.total * Decimal(100)))
    if payment.client_secret:
        return payment, None
    if payment.paymob_order_id:
        return None, PaymentStartError("needs_review", "An identified payment needs review before retrying.", 409)
    payment.intention_state = Payment.CREATING
    payment.save(update_fields=["intention_state"])
    return payment, None
