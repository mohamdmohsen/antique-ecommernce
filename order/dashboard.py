from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from catalog.models import Product
from payments.models import Payment
from users.models import User
from .models import Order
from .services import orders_awaiting_shipping

# Days are counted in the shop's own time zone, not UTC.
SHOP_TZ = ZoneInfo("Africa/Cairo")

# An order counts as sold once it is paid (or later in its life).
PAID_STATUSES = [Order.PAID, Order.SHIPPED, Order.DELIVERED]


def cents_to_money(cents):
    return Decimal(cents) / 100


def overview(request):
    """Owner overview page. Wrapped in admin.site.admin_view() in urls.py,
    so only logged-in staff can open it."""
    if not request.user.has_perms(["order.view_order", "payments.view_payment"]):
        raise PermissionDenied

    days = 30 if request.GET.get("days") == "30" else 7

    # Revenue = successful payments on paid orders. A refunded payment has the
    # status "refunded", so refunds drop out of the total by themselves.
    sales = Payment.objects.filter(
        status=Payment.SUCCEEDED, order__status__in=PAID_STATUSES
    )
    revenue_cents = sales.aggregate(total=Sum("amount_cents"))["total"] or 0
    paid_orders = sales.values("order").distinct().count()

    # Sales per day for the chart (days without sales show as zero).
    first_day = timezone.now().astimezone(SHOP_TZ).date() - timedelta(days=days - 1)
    start = datetime.combine(first_day, time.min, tzinfo=SHOP_TZ)
    per_day = {
        row["day"]: row["total"]
        for row in sales.filter(succeeded_at__gte=start)
        .annotate(day=TruncDate("succeeded_at", tzinfo=SHOP_TZ))
        .values("day")
        .annotate(total=Sum("amount_cents"))
    }
    rows = [
        (first_day + timedelta(days=i), per_day.get(first_day + timedelta(days=i), 0))
        for i in range(days)
    ]
    biggest = max((cents for _, cents in rows), default=0)
    chart = [
        {
            "date": day,
            "amount": cents_to_money(cents),
            # bar height in percent; a tiny bar is still visible if there was a sale
            "pct": max(round(cents * 100 / biggest), 3) if cents else 0,
        }
        for day, cents in rows
    ]

    context = {
        **admin.site.each_context(request),
        "title": "Shop overview",
        "days": days,
        "revenue": cents_to_money(revenue_cents),
        "paid_orders": paid_orders,
        "awaiting_payment": Order.objects.filter(status=Order.PENDING).count(),
        "awaiting_shipping": orders_awaiting_shipping().count(),
        "undated_sales": sales.filter(succeeded_at__isnull=True).count(),
        "needs_attention": Payment.objects.filter(needs_attention=True).count(),
        "customers": User.objects.filter(is_staff=False, is_superuser=False).count(),
        "products": Product.objects.count(),
        "sold_out": Product.objects.filter(stock=0).count(),
        "chart": chart,
        "sales_days": [d for d in reversed(chart) if d["amount"]],  # newest first, no empty days
        "period_total": cents_to_money(sum(cents for _, cents in rows)),
    }
    return render(request, "admin/overview.html", context)
