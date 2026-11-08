"""PostHog product analytics, sent from the server only.

What it is for: answering "where do customers drop off?" (cart -> order -> payment ->
paid) from a handful of business events.

Rules this file enforces:
* No POSTHOG_API_KEY in .env  -> analytics is OFF: nothing is sent, nothing is queued.
* An event is sent only AFTER the database transaction that caused it commits, so an
  order that was rolled back is never counted.
* Sending is asynchronous (the SDK queues and sends in a background thread) and can
  never break a checkout: every failure is caught and logged.
* Customers are identified only by their internal user id. Properties named like
  personal data (email, phone, address, name, password, tokens...) are dropped, and
  GeoIP lookup is turned off.
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.db import transaction

from .glitchtip import SENSITIVE_KEYS

logger = logging.getLogger(__name__)

_client = None


def is_enabled():
    return bool(settings.POSTHOG_API_KEY)


def get_client():
    """Create the PostHog client on first use (so settings and tests can change it)."""
    global _client
    if _client is None:
        from posthog import Posthog

        _client = Posthog(
            settings.POSTHOG_API_KEY,
            host=settings.POSTHOG_HOST,
            disable_geoip=True,
            enable_exception_autocapture=False,  # errors belong in GlitchTip, not here
        )
    return _client


def _clean(properties):
    """Only plain, non-personal values leave the server."""
    cleaned = {}
    for key, value in properties.items():
        if value is None or str(key).lower().replace("-", "_") in SENSITIVE_KEYS:
            continue
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()
        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
    cleaned["environment"] = settings.POSTHOG_ENVIRONMENT
    return cleaned


def track(event, user_id, **properties):
    """Queue one event for `user_id`; it is sent once the surrounding transaction commits."""
    if not is_enabled():
        return
    distinct_id = str(user_id)
    payload = _clean(properties)

    def send():
        try:
            get_client().capture(event, distinct_id=distinct_id, properties=payload)
        except Exception:
            logger.warning("PostHog event %r was not sent", event, exc_info=True)

    transaction.on_commit(send)
