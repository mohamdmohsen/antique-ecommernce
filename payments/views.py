import logging

from rest_framework import status
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, throttle_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from users.throttles import WebhookThrottle
from .models import WebhookEvent
from .paymob import verify_hmac
from .services import (
    PaymentStartError, apply_transaction_result, start_payment_for_order,
)

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_payment(request, order_id):
    try:
        checkout_url = start_payment_for_order(order_id, request.user)
    except PaymentStartError as error:
        return Response({"error": error.message}, status=error.status)
    return Response({"checkout_url": checkout_url})


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
