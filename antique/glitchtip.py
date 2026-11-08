"""GlitchTip error reporting (GlitchTip speaks the Sentry protocol).

What it does: when the shop raises an unhandled error (a 500 page) or logs an
ERROR (for example "Paymob intention failed"), a report is sent to GlitchTip so
the operator can see it in a dashboard instead of waiting for a customer to complain.

Rules this file enforces:
* No GLITCHTIP_DSN in .env  -> reporting is OFF and nothing is sent (local dev, tests).
* Never send secrets or customer data: no request bodies, cookies, local variables,
  and every sensitive header/field/query parameter is replaced by "[Filtered]".
* Reporting must never break the shop: a bad DSN is logged and ignored.
"""

import logging
from urllib.parse import parse_qsl, urlencode

import sentry_sdk
from django.core.exceptions import DisallowedHost
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

logger = logging.getLogger(__name__)

FILTERED = "[Filtered]"

# Added to the SDK's own list (password, token, secret, cookie, ...).
# Names are compared in lower case, with "-" treated like "_".
EXTRA_SENSITIVE_KEYS = [
    "hmac",             # Paymob webhook signature (arrives in the query string)
    "client_secret",    # Paymob checkout secret
    "paymob_secret_key",
    "paymob_hmac_secret",
    "paymob_api_key",
    "refresh",          # JWT refresh token
    "access",           # JWT access token
    "pan",              # card number fields in Paymob payloads
    "cvv",
    "card_number",
    "phone",
    "email",
    "address",
    "full_name",
]
SENSITIVE_KEYS = {key.lower().replace("-", "_") for key in [*DEFAULT_DENYLIST, *EXTRA_SENSITIVE_KEYS]}


def _is_sensitive(name):
    return str(name).lower().replace("-", "_") in SENSITIVE_KEYS


def _filter_query(query_string):
    """Keep the shape of the query string but hide the value of sensitive parameters."""
    pairs = parse_qsl(query_string, keep_blank_values=True)
    return urlencode([(k, FILTERED if _is_sensitive(k) else v) for k, v in pairs], safe="[]")


def scrub_event(event, hint):
    """Last line of defence, runs on every event just before it leaves the server."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)      # request body: card/payment/customer data
        request.pop("cookies", None)   # session and CSRF cookies
        query_string = request.get("query_string")
        if isinstance(query_string, str) and query_string:
            request["query_string"] = _filter_query(query_string)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for name in list(headers):
                if _is_sensitive(name):
                    headers[name] = FILTERED
    return event


def sentry_options(dsn, environment, release=None, **extra):
    """The full SDK configuration. Kept separate from init so tests can use it too."""
    options = {
        "dsn": dsn,
        "environment": environment,
        "release": release,
        "integrations": [
            DjangoIntegration(),
            # ERROR logs become reports; INFO/WARNING are kept only as breadcrumbs.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        "send_default_pii": False,           # no IP addresses, no user email
        "include_local_variables": False,    # tracebacks must not carry variable values
        "max_request_body_size": "never",    # never attach request bodies
        "traces_sample_rate": 0,             # errors only, no performance tracing
        "event_scrubber": EventScrubber(
            denylist=[*DEFAULT_DENYLIST, *EXTRA_SENSITIVE_KEYS], recursive=True
        ),
        "before_send": scrub_event,
        # bots sending a wrong Host header would otherwise flood the dashboard
        "ignore_errors": [DisallowedHost],
    }
    options.update(extra)
    return options


def init_glitchtip(dsn, environment, release=None):
    """Turn reporting on. Returns True when it is active."""
    if not dsn:
        return False
    try:
        sentry_sdk.init(**sentry_options(dsn, environment, release))
    except Exception:  # a typo in the DSN must not stop the shop from starting
        logger.error("GlitchTip is disabled: GLITCHTIP_DSN is invalid.")
        return False
    return True
