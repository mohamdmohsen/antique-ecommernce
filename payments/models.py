from django.db import models

from django.db import models
from django.db.models import Q

from antique.admin_i18n import t
from order.models import Order


class Payment(models.Model):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    STATUS_CHOICES = [
        (PENDING, t("Pending")),
        (SUCCEEDED, t("Succeeded")),
        (FAILED, t("Failed")),
        (REFUNDED, t("Refunded")),
    ]

    NEW = "new"
    CREATING = "creating"
    READY = "ready"
    UNKNOWN = "unknown"
    intention_state = models.CharField(verbose_name=t("intention state"), max_length=10, default=NEW,
        choices=[(NEW, t("Not started")), (CREATING, t("Creating checkout")),
                 (READY, t("Checkout identified")), (UNKNOWN, t("Needs reconciliation"))])

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments", verbose_name=t("order"))
    status = models.CharField(verbose_name=t("status"), max_length=10, choices=STATUS_CHOICES, default=PENDING)
    amount_cents = models.PositiveIntegerField(verbose_name=t("amount cents"))
    currency = models.CharField(verbose_name=t("currency"), max_length=3, default="EGP")
    client_secret = models.CharField(verbose_name=t("client secret"), max_length=255, blank=True)
    # Paymob's own order id: the callback is matched to this payment by this value,
    # because Paymob signs it (it is part of the HMAC), unlike our own reference.
    paymob_order_id = models.CharField(verbose_name=t("paymob order id"), max_length=50, blank=True, db_index=True)
    paymob_transaction_id = models.CharField(verbose_name=t("paymob transaction id"), max_length=50, null=True, blank=True, unique=True)
    needs_attention = models.BooleanField(verbose_name=t("needs attention"), default=False)
    note = models.TextField(verbose_name=t("note"), blank=True)
    created_at = models.DateTimeField(verbose_name=t("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name=t("updated at"), auto_now=True)
    # First accepted success confirmation; never inferred from mutable update times.
    succeeded_at = models.DateTimeField(verbose_name=t("succeeded at"), null=True, blank=True, editable=False, db_index=True)

    class Meta:
        verbose_name = t("payment")
        verbose_name_plural = t("payments")
        constraints = [
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(status="pending"),
                name="one_pending_payment_per_order",
            )
        ]

    def __str__(self):
        return t("Payment %(id)s for order %(order)s (%(status)s)") % {
            "id": self.pk, "order": self.order_id, "status": self.get_status_display()}


class WebhookEvent(models.Model):
    transaction_id = models.CharField(verbose_name=t("transaction id"), max_length=50, blank=True)
    payload = models.JSONField(verbose_name=t("payload"))
    hmac_valid = models.BooleanField(verbose_name=t("hmac valid"))
    created_at = models.DateTimeField(verbose_name=t("created at"), auto_now_add=True)

    class Meta:
        verbose_name = t("webhook event")
        verbose_name_plural = t("webhook events")

class Refund(models.Model):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    UNKNOWN = "unknown"
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="refund", verbose_name=t("payment"))
    requested_by = models.ForeignKey("users.User", on_delete=models.PROTECT, null=True, blank=True, verbose_name=t("requested by"))
    amount_cents = models.PositiveIntegerField(verbose_name=t("amount cents"))
    status = models.CharField(verbose_name=t("status"), max_length=10, default=PENDING, choices=[(PENDING, t("Pending")), (SUCCEEDED, t("Succeeded")), (UNKNOWN, t("Needs reconciliation"))])
    provider_id = models.CharField(verbose_name=t("provider id"), max_length=50, blank=True)
    note = models.TextField(verbose_name=t("note"), blank=True)
    created_at = models.DateTimeField(verbose_name=t("created at"), auto_now_add=True)

    class Meta:
        verbose_name = t("refund")
        verbose_name_plural = t("refunds")

    def __str__(self):
        return t("Refund %(id)s for payment %(payment)s (%(status)s)") % {
            "id": self.pk, "payment": self.payment_id, "status": self.get_status_display()}
