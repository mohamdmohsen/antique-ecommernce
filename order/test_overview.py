from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import Product
from payments.models import Payment
from users.models import User
from .models import Order


@override_settings(SECURE_SSL_REDIRECT=False)
class OverviewPageTests(TestCase):
    def setUp(self):
        self.url = reverse("admin_overview")
        self.customer = User.objects.create_user("buyer", "buyer@example.com", "pw-not-used-1")
        self.owner = User.objects.create_superuser("owner", "owner@example.com", "pw-not-used-2")

    def make_order(self, status, payment_status, cents):
        order = Order.objects.create(
            user=self.customer, status=status, total=Decimal(cents) / 100,
            full_name="A B", phone="1", address="x", city="c",
        )
        Payment.objects.create(
            order=order, status=payment_status, amount_cents=cents,
            succeeded_at=timezone.now() if payment_status == Payment.SUCCEEDED else None,
        )
        return order

    # ---- who can open it ----
    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_customer_is_sent_to_login(self):
        self.client.force_login(self.customer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_staff_without_permission_gets_403(self):
        clerk = User.objects.create_user("clerk", "clerk@example.com", "pw-not-used-3", is_staff=True)
        self.client.force_login(clerk)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    # ---- the numbers ----
    def test_numbers_only_count_real_sales(self):
        self.make_order(Order.PAID, Payment.SUCCEEDED, 10000)       # counts
        self.make_order(Order.SHIPPED, Payment.SUCCEEDED, 5000)     # counts
        self.make_order(Order.PENDING, Payment.PENDING, 7000)       # not paid yet
        self.make_order(Order.PAID, Payment.REFUNDED, 9000)         # refunded: no revenue, nothing to ship
        late = self.make_order(Order.CANCELLED, Payment.SUCCEEDED, 4000)  # paid after cancel
        Payment.objects.filter(order=late).update(needs_attention=True)

        Product.objects.create(title="Clock", price=Decimal("100"), image="products/a.jpg", stock=1)
        Product.objects.create(title="Vase", price=Decimal("80"), image="products/b.jpg", stock=0)

        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        ctx = response.context

        self.assertEqual(ctx["revenue"], Decimal("150.00"))
        self.assertEqual(ctx["paid_orders"], 2)
        self.assertEqual(ctx["awaiting_payment"], 1)
        self.assertEqual(ctx["awaiting_shipping"], 1)
        self.assertEqual(ctx["needs_attention"], 1)
        self.assertEqual(ctx["customers"], 1)      # the owner is not a customer
        self.assertEqual(ctx["products"], 2)
        self.assertEqual(ctx["sold_out"], 1)

    def test_chart_has_one_bar_per_day_and_today_holds_the_sales(self):
        self.make_order(Order.PAID, Payment.SUCCEEDED, 10000)
        self.client.force_login(self.owner)

        context = self.client.get(self.url).context
        chart = context["chart"]
        self.assertEqual(len(context["sales_days"]), 1)  # the table skips empty days
        self.assertEqual(len(chart), 7)
        self.assertEqual(chart[-1]["amount"], Decimal("100.00"))
        self.assertEqual(chart[-1]["pct"], 100)
        self.assertEqual(chart[0]["amount"], Decimal("0"))

    def test_thirty_day_view_and_bad_value(self):
        self.client.force_login(self.owner)
        self.assertEqual(len(self.client.get(self.url + "?days=30").context["chart"]), 30)
        self.assertEqual(len(self.client.get(self.url + "?days=999").context["chart"]), 7)

    def test_empty_shop_does_not_crash(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["revenue"], Decimal("0"))

    def test_admin_home_has_the_link(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, self.url)
