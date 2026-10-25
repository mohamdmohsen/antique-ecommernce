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
    paymob_transaction_id = models.CharField(max_length=50, null=True, blank=True, unique=True)
    needs_attention = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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