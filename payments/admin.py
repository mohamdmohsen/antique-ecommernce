from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from .models import Payment, Refund, WebhookEvent
from .services import request_full_refund


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "status", "amount_cents", "currency", "needs_attention", "updated_at")
    list_filter = ("needs_attention", "status", "currency")
    search_fields = ("=id", "=order__id", "paymob_transaction_id", "paymob_order_id")
    readonly_fields = tuple(field.name for field in Payment._meta.fields if field.name not in {"needs_attention", "note"})
    actions = ["refund_full_payment"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Request full refund for selected successful payments", permissions=["change"])
    def refund_full_payment(self, request, queryset):
        for payment in queryset:
            try:
                refund = request_full_refund(payment.pk, request.user)
                self.message_user(request, f"Payment {payment.pk}: refund {refund.status}.")
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), messages.ERROR)


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("id", "payment", "status", "amount_cents", "requested_by", "created_at")
    list_filter = ("status",)
    readonly_fields = tuple(field.name for field in Refund._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("id", "transaction_id", "hmac_valid", "created_at")
    readonly_fields = tuple(field.name for field in WebhookEvent._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
