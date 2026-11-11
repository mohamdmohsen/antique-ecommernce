from django.conf import settings
from django.db import models

from antique.admin_i18n import t
from catalog.models import Product


class Order(models.Model):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (PENDING, t("Pending")),
        (PAID, t("Paid")),
        (SHIPPED, t("Shipped")),
        (DELIVERED, t("Delivered")),
        (CANCELLED, t("Cancelled")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders",
        verbose_name=t("user"),
    )
    status = models.CharField(verbose_name=t("status"), max_length=10, choices=STATUS_CHOICES, default=PENDING)
    total = models.DecimalField(verbose_name=t("total"), max_digits=10, decimal_places=2)

    # shipping address, copied at the time of the order
    full_name = models.CharField(verbose_name=t("full name"), max_length=150)
    phone = models.CharField(verbose_name=t("phone"), max_length=20)
    address = models.CharField(verbose_name=t("address"), max_length=255)
    city = models.CharField(verbose_name=t("city"), max_length=100)

    tracking_number = models.CharField(verbose_name=t("tracking number"), max_length=150, blank=True)
    created_at = models.DateTimeField(verbose_name=t("created at"), auto_now_add=True)

    class Meta:
        verbose_name = t("order")
        verbose_name_plural = t("orders")

    def __str__(self):
        return t("Order %(id)s - %(user)s") % {"id": self.pk, "user": self.user}


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", verbose_name=t("order"))
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name=t("product"))
    title = models.CharField(verbose_name=t("title"), max_length=200)
    price = models.DecimalField(verbose_name=t("price"), max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(verbose_name=t("quantity"))

    class Meta:
        verbose_name = t("order item")
        verbose_name_plural = t("order items")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="order_item_quantity_gte_1",
        )
    ]

    def __str__(self):
        return f"{self.title} x {self.quantity}"

class OrderStatusEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="status_events", verbose_name=t("order"))
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name=t("actor"))
    previous_status = models.CharField(verbose_name=t("previous status"), max_length=10)
    status = models.CharField(verbose_name=t("status"), max_length=10)
    created_at = models.DateTimeField(verbose_name=t("created at"), auto_now_add=True)

    class Meta:
        verbose_name = t("order status event")
        verbose_name_plural = t("order status events")
