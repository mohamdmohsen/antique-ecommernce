import logging
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated

from .models import Payment, WebhookEvent
from .paymob import create_intention, verify_hmac
from .services import apply_transaction_result, flag_for_reconciliation, needs_reconciliation

from order.models import Order
from .models import Payment
from .paymob import create_intention

from users.throttles import WebhookThrottle

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_payment(request, order_id):
    # The order row is locked until this block ends, so two clicks at the same
    # moment run one after the other: only ONE call to Paymob per payment.
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(), pk=order_id, user=request.user
        )

        if order.status != Order.PENDING:
            return Response({"error": "Order cannot be paid"}, status=status.HTTP_400_BAD_REQUEST)

        # An earlier checkout may still take payment. Do not replace it or offer
        # another checkout until its provider identity has been reconciled.
        for previous in order.payments.select_for_update().order_by("pk"):
            if needs_reconciliation(previous):
                flag_for_reconciliation(previous)
                return Response(
                    {"error": "An existing payment needs review. Please contact support before retrying."},
                    status=status.HTTP_409_CONFLICT,
                )

        deadline = order.created_at + timedelta(minutes=settings.ORDER_PAYMENT_WINDOW_MINUTES)
        if timezone.now() > deadline:
            return Response({"error": "Order expired"}, status=status.HTTP_400_BAD_REQUEST)

        payment = Payment.objects.filter(order=order, status=Payment.PENDING).first()
        if payment is None:
            amount_cents = int((order.total * Decimal(100)).to_integral_value())
            payment = Payment.objects.create(order=order, amount_cents=amount_cents)

        if not payment.client_secret:
            try:
                payment.client_secret, payment.paymob_order_id = create_intention(payment)
                payment.save(update_fields=["client_secret", "paymob_order_id"])
            except (requests.RequestException, KeyError, ValueError):
                logger.exception("Paymob intention failed for payment %s", payment.id)
                payment.status = Payment.FAILED
                payment.note = "Could not create payment intention"
                payment.save(update_fields=["status", "note"])
                return Response(
                    {"error": "Payment service unavailable, please try again"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

    query = urlencode({
        "publicKey": settings.PAYMOB_PUBLIC_KEY,
        "clientSecret": payment.client_secret,
    })
    return Response({"checkout_url": f"{settings.PAYMOB_CHECKOUT_URL}?{query}"})



@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([WebhookThrottle])
def paymob_webhook(request):
    payload = request.data
    obj = payload.get("obj") if isinstance(payload, dict) else None
    if not isinstance(obj, dict):
        return Response(status=status.HTTP_400_BAD_REQUEST)

    received = request.query_params.get("hmac") or payload.get("hmac")
    valid = verify_hmac(obj, received)

    if not valid:
        return Response(status=status.HTTP_400_BAD_REQUEST)

    WebhookEvent.objects.create(
        transaction_id=str(obj.get("id", ""))[:50],
        payload=payload,
        hmac_valid=valid,
    )

    if payload.get("type") == "TRANSACTION":
        apply_transaction_result(obj)
    return Response(status=status.HTTP_200_OK)
