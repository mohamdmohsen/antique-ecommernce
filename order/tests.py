import threading
import time
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from cart.models import CartItem
from catalog.models import Product
from payments.models import Payment
from users.models import User
from .models import Order, OrderItem

SHIPPING = {"full_name": "Ali Hassan", "phone": "01000000000", "address": "1 Street", "city": "Cairo"}


class ExpiryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ali", email="ali@test.com", password="Str0ng#Pass2026")
        self.product = Product.objects.create(title="Clock", price=Decimal("10.00"), image="products/a.jpg", stock=8)

    def order(self, minutes_old, quantity=2, status=Order.PENDING):
        order = Order.objects.create(user=self.user, total=Decimal("20.00"), status=status, **SHIPPING)
        OrderItem.objects.create(order=order, product=self.product, title="Clock", price=Decimal("10.00"), quantity=quantity)
        # created_at is auto_now_add, so move it back with update()
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_old))
        return order

    def test_old_unpaid_order_is_cancelled_and_stock_returns_once(self):
        order = self.order(minutes_old=60)
        payment = Payment.objects.create(order=order, amount_cents=2000)
        call_command("cancel_expired_orders")
        call_command("cancel_expired_orders")  # a second run must not return stock again
        order.refresh_from_db()
        payment.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.CANCELLED)
        self.assertEqual(payment.status, Payment.FAILED)
        self.assertEqual(self.product.stock, 10)

    def test_recent_order_is_left_alone(self):
        order = self.order(minutes_old=5)
        call_command("cancel_expired_orders")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PENDING)

    def test_order_inside_the_grace_period_is_left_alone(self):
        order = self.order(minutes_old=35)  # past the 30 minute window, before 30 + 10
        call_command("cancel_expired_orders")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PENDING)

    def test_paid_order_is_never_cancelled(self):
        order = self.order(minutes_old=60, status=Order.PAID)
        call_command("cancel_expired_orders")
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((order.status, self.product.stock), (Order.PAID, 8))

    def test_pending_order_with_a_succeeded_payment_is_left_for_a_person(self):
        order = self.order(minutes_old=60)
        Payment.objects.create(order=order, amount_cents=2000, status=Payment.SUCCEEDED)
        call_command("cancel_expired_orders")
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((order.status, self.product.stock), (Order.PENDING, 8))


@skipUnless(connection.features.has_select_for_update, "needs PostgreSQL: SQLite cannot lock rows")
@override_settings(SECURE_SSL_REDIRECT=False)
class ConcurrencyTests(TransactionTestCase):
    """Real threads against a real database. These only run on PostgreSQL."""

    def run_in_threads(self, jobs):
        barrier = threading.Barrier(len(jobs))
        results = [None] * len(jobs)

        def worker(index, job):
            try:
                barrier.wait()
                results[index] = job()
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def test_two_customers_cannot_both_buy_the_last_unit(self):
        product = Product.objects.create(title="Last clock", price=Decimal("10.00"), image="products/a.jpg", stock=1)
        users = [User.objects.create_user(username=f"u{i}", email=f"u{i}@test.com", password="Str0ng#Pass2026") for i in range(2)]
        for user in users:
            CartItem.objects.create(user=user, product=product, quantity=1)

        def checkout(user):
            def job():
                client = APIClient()
                client.force_authenticate(user)
                return client.post("/api/order/checkout/", SHIPPING, format="json").status_code
            return job

        codes = sorted(self.run_in_threads([checkout(u) for u in users]))
        product.refresh_from_db()
        self.assertEqual(codes, [201, 400])
        self.assertEqual(product.stock, 0)
        self.assertEqual(Order.objects.count(), 1)

    def test_two_clicks_on_pay_call_paymob_only_once(self):
        user = User.objects.create_user(username="ali", email="ali@test.com", password="Str0ng#Pass2026")
        product = Product.objects.create(title="Clock", price=Decimal("10.00"), image="products/a.jpg", stock=5)
        order = Order.objects.create(user=user, total=Decimal("10.00"), **SHIPPING)
        OrderItem.objects.create(order=order, product=product, title="Clock", price=Decimal("10.00"), quantity=1)

        def slow_intention(payment):
            time.sleep(0.4)  # keep the first call busy so the second click really overlaps it
            return "secret", "7001"

        def pay():
            client = APIClient()
            client.force_authenticate(user)
            return client.post(f"/api/payments/orders/{order.id}/pay/").status_code

        with patch("payments.services.create_intention", side_effect=slow_intention) as mocked:
            codes = self.run_in_threads([pay, pay])

        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)

    def test_two_checkouts_of_one_cart_create_one_order(self):
        user = User.objects.create_user(username="ali", email="ali@test.com", password="Str0ng#Pass2026")
        product = Product.objects.create(title="Clock", price=Decimal("10.00"), image="products/a.jpg", stock=5)
        CartItem.objects.create(user=user, product=product, quantity=1)
        original = Product.objects.select_for_update

        def slow_product_lock(*args, **kwargs):
            # Keep the first request busy after it has read and locked the cart.
            time.sleep(0.2)
            return original(*args, **kwargs)

        def checkout():
            client = APIClient()
            client.force_authenticate(user)
            return client.post("/api/order/checkout/", SHIPPING, format="json").status_code

        with patch("order.services.Product.objects.select_for_update", side_effect=slow_product_lock):
            codes = self.run_in_threads([checkout, checkout])

        product.refresh_from_db()
        self.assertEqual(sorted(codes), [201, 400])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(product.stock, 4)
