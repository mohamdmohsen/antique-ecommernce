from django.db import models

from django.db import models
from django.db.models import Q

from order.models import Order


class Payment(models.Model):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (SUCCEEDED, "Succeeded"),
        (FAILED, "Failed"),
        (REFUNDED, "Refunded"),
    ]

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="EGP")
    client_secret = models.CharField(max_length=255, blank=True)
    # Paymob's own order id: the callback is matched to this payment by this value,
    # because Paymob signs it (it is part of the HMAC), unlike our own reference.
    paymob_order_id = models.CharField(max_length=50, blank=True, db_index=True)
    paymob_transaction_id = models.CharField(max_length=50, null=True, blank=True, unique=True)
    needs_attention = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # First accepted success confirmation; never inferred from mutable update times.
    succeeded_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(status="pending"),
                name="one_pending_payment_per_order",
            )
        ]

    def __str__(self):
        return f"Payment {self.pk} for order {self.order_id} ({self.status})"


class WebhookEvent(models.Model):
    transaction_id = models.CharField(max_length=50, blank=True)
    payload = models.JSONField()
    hmac_valid = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

class Refund(models.Model):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    UNKNOWN = "unknown"
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="refund")
    requested_by = models.ForeignKey("users.User", on_delete=models.PROTECT, null=True, blank=True)
    amount_cents = models.PositiveIntegerField()
    status = models.CharField(max_length=10, default=PENDING, choices=[(PENDING, "Pending"), (SUCCEEDED, "Succeeded"), (UNKNOWN, "Needs reconciliation")])
    provider_id = models.CharField(max_length=50, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Refund {self.pk} for payment {self.payment_id} ({self.status})"
