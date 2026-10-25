import requests
from django.conf import settings
import hashlib
import hmac


def create_intention(payment):
    order = payment.order
    first_name, _, last_name = order.full_name.partition(" ")

    body = {
        "amount": payment.amount_cents,
        "currency": payment.currency,
        "payment_methods": [int(settings.PAYMOB_INTEGRATION_ID)],
        "items": [
            {
                "name": item.title,
                "amount": int(item.price * 100),
                "quantity": item.quantity,
            }
            for item in order.items.all()
        ],
        "billing_data": {
            "first_name": first_name,
            "last_name": last_name or "NA",
            "phone_number": order.phone,
            "email": order.user.email,
        },
        "special_reference": f"pay-{payment.id}",
        "notification_url": settings.PAYMOB_NOTIFICATION_URL,
        "redirection_url": settings.PAYMOB_REDIRECTION_URL,
    }

    response = requests.post(
        settings.PAYMOB_INTENTION_URL,
        json=body,
        headers={"Authorization": f"Token {settings.PAYMOB_SECRET_KEY}"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return data["client_secret"], str(data["intention_order_id"])


HMAC_FIELDS = [
    "amount_cents", "created_at", "currency", "error_occured",
    "has_parent_transaction", "obj.id", "integration_id", "is_3d_secure",
    "is_auth", "is_capture", "is_refunded", "is_standalone_payment",
    "is_voided", "order.id", "owner", "pending",
    "source_data.pan", "source_data.sub_type", "source_data.type", "success",
]


def _get(obj, path):
    value = obj
    for part in path.split("."):
        if not isinstance(value, dict):
            return ""
        value = value.get(part, "")
    return value


def _to_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def verify_hmac(obj, received):
    if not received:
        return False
    message = ""
    for field in HMAC_FIELDS:
        path = "id" if field == "obj.id" else field   # obj.id = the transaction's own id
        message += _to_text(_get(obj, path))
    expected = hmac.new(
        settings.PAYMOB_HMAC_SECRET.encode(), message.encode(), hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected.encode(), str(received).encode())