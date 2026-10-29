import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.throttling import BaseThrottle

from .models import RateLimitBucket
from .client_ip import client_ip


class AccountThrottle(BaseThrottle):
    scope = "account"
    ip_limit = 30
    identity_limit = 10
    window = 60

    def allow_request(self, request, view):
        # Forwarding headers only influence limits through explicit peer trust.
        data = request.data if isinstance(request.data, dict) else {}
        identity = str(data.get("username") or data.get("email") or "").strip().casefold()[:254]
        limits = [("ip", client_ip(request.META), self.ip_limit)]
        if identity:
            limits.append(("account", identity, self.identity_limit))
        allowed = True
        self.retry_after = 1
        for kind, value, limit in limits:
            key = hashlib.sha256(f"{self.scope}:{kind}:{value}".encode()).hexdigest()
            with transaction.atomic():
                now = timezone.now()
                bucket, _ = RateLimitBucket.objects.select_for_update().get_or_create(
                    key=key, defaults={"expires_at": now + timedelta(seconds=self.window)}
                )
                if bucket.expires_at <= now:
                    bucket.count = 0
                    bucket.expires_at = now + timedelta(seconds=self.window)
                if bucket.count >= limit:
                    allowed = False
                    self.retry_after = max(self.retry_after, (bucket.expires_at - now).total_seconds())
                else:
                    bucket.count += 1
                bucket.save(update_fields=["count", "expires_at"])
            if not allowed:
                return False
        return allowed

    def wait(self):
        return self.retry_after


class LoginThrottle(AccountThrottle):
    scope = "login"


class EmailThrottle(AccountThrottle):
    scope = "email"
    ip_limit = 10
    identity_limit = 3
    window = 3600


class WebhookThrottle(AccountThrottle):
    scope = "webhook"
    ip_limit = 1200
    identity_limit = 1200
