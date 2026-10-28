from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from .models import Order, OrderItem, OrderStatusEvent
from .services import transition_order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "total", "tracking_number", "created_at")
    list_filter = ("status",)
    search_fields = ("=id", "user__username", "tracking_number")
    readonly_fields = ("user", "status", "total", "created_at")
    actions = ["mark_shipped", "mark_delivered"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def transition(self, request, queryset, target):
        for order in queryset:
            try:
                transition_order(order.pk, target, request.user)
                self.message_user(request, f"Order {order.pk}: {target}.")
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), messages.ERROR)

    @admin.action(description="Mark selected paid orders shipped", permissions=["change"])
    def mark_shipped(self, request, queryset):
        self.transition(request, queryset, Order.SHIPPED)

    @admin.action(description="Mark selected shipped orders delivered", permissions=["change"])
    def mark_delivered(self, request, queryset):
        self.transition(request, queryset, Order.DELIVERED)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    readonly_fields = tuple(field.name for field in OrderItem._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderStatusEvent)
class StatusEventAdmin(admin.ModelAdmin):
    list_display = ("order", "previous_status", "status", "actor", "created_at")
    readonly_fields = tuple(field.name for field in OrderStatusEvent._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


# Adds the "Shop overview" link at the top of the admin home page.
admin.site.index_template = "admin/shop_index.html"
