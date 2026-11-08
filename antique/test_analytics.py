import json
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase, override_settings

from antique import analytics
from cart.models import CartItem
from cart.services import add_item
from catalog.models import Product
from order.models import Order
from order.services import cancel_if_unpaid, create_order_with_policy
from payments.models import Payment
from payments.services import apply_transaction_result, start_payment_for_order
from users.models import User
from users.policies import register_customer

PII = {"email": "buyer@example.invalid", "phone": "01000000000", "address": "12 Secret Street", "full_name": "Real Name"}


class Boom(Exception):
    pass


@override_settings(POSTHOG_API_KEY="phc_test", POSTHOG_ENVIRONMENT="test")
class AnalyticsCase(TestCase):
    """Base: a fake PostHog client, and a helper that runs code and returns what was sent."""

    def setUp(self):
        self.client_mock = MagicMock()
        patcher = patch("antique.analytics.get_client", return_value=self.client_mock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self, action):
        """Run `action()` like a request would (callbacks run at commit); return events sent."""
        self.client_mock.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            action()
        return [(c.args[0], c.kwargs) for c in self.client_mock.capture.call_args_list]

    def names(self, events):
        return [name for name, _ in events]


class TrackTests(AnalyticsCase):
    def test_properties_are_cleaned_and_personal_data_is_dropped(self):
        user_id = uuid4()
        events = self.sent(lambda: analytics.track(
            "demo", user_id, total=Decimal("12.50"), order_id=7, gift=True, nothing=None, **PII
        ))
        (name, kwargs), = events
        self.assertEqual(name, "demo")
        self.assertEqual(kwargs["distinct_id"], str(user_id))
        self.assertEqual(kwargs["properties"], {"total": 12.5, "order_id": 7, "gift": True, "environment": "test"})
        self.assertNotIn("Secret", json.dumps(kwargs, default=str))

    def test_event_is_discarded_when_the_transaction_rolls_back(self):
        def failing_checkout():
            try:
                with transaction.atomic():
                    analytics.track("order_created", 1, order_id=1)
                    raise Boom
            except Boom:
                pass

        self.assertEqual(self.sent(failing_checkout), [])

    def test_a_broken_posthog_never_breaks_the_shop(self):
        self.client_mock.capture.side_effect = RuntimeError("PostHog is down")
        with self.assertLogs("antique.analytics", "WARNING"):
            self.sent(lambda: analytics.track("demo", 1))  # must not raise

    @override_settings(POSTHOG_API_KEY="")
    def test_without_a_key_nothing_is_queued_or_sent(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            analytics.track("demo", 1)
        self.assertEqual(callbacks, [])
        self.client_mock.capture.assert_not_called()


class ShopEventTests(AnalyticsCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("buyer", "buyer@example.invalid", "synthetic-only")
        self.product = Product.objects.create(title="Clock", price=Decimal("10"), stock=10, image="products/test.jpg")

    def checkout(self):
        add_item(self.user, self.product.pk, 2)
        return create_order_with_policy(self.user, {
            "full_name": "Real Name", "phone": "01000000000", "address": "12 Secret Street",
            "city": "Cairo", "terms_accepted": True, "buyer_confirmed": True,
        })

    def paid_event(self, payment, **overrides):
        return {"order": {"id": "1234", "merchant_order_id": f"pay-{payment.pk}"}, "id": "5678", "success": True,
                "pending": False, "amount_cents": payment.amount_cents, "currency": "EGP", **overrides}

    def pending_payment(self):
        order = self.checkout()
        return Payment.objects.create(order=order, amount_cents=2000, paymob_order_id="1234")

    def test_registration(self):
        events = self.sent(lambda: register_customer(
            username="new", email="new@example.invalid", password="synthetic-only-9",
            age_confirmed=True, terms_accepted=True))
        (name, kwargs), = events
        self.assertEqual(name, "user_registered")
        self.assertEqual(kwargs["distinct_id"], str(User.objects.get(username="new").pk))
        self.assertNotIn("new@example.invalid", json.dumps(kwargs, default=str))

    def test_add_to_cart(self):
        events = self.sent(lambda: add_item(self.user, self.product.pk, 2))
        self.assertEqual(events, [("cart_item_added", {
            "distinct_id": str(self.user.pk),
            "properties": {"product_id": self.product.pk, "quantity": 2, "cart_quantity": 2, "environment": "test"},
        })])

    def test_failed_add_to_cart_sends_nothing(self):
        from cart.services import CartError

        def too_many():
            with self.assertRaises(CartError):
                add_item(self.user, self.product.pk, 999)

        self.assertEqual(self.sent(too_many), [])

    def test_checkout_sends_order_created_without_the_address(self):
        add_item(self.user, self.product.pk, 2)
        events = self.sent(lambda: create_order_with_policy(self.user, {
            "full_name": "Real Name", "phone": "01000000000", "address": "12 Secret Street",
            "city": "Cairo", "terms_accepted": True, "buyer_confirmed": True}))
        (name, kwargs), = events
        self.assertEqual(name, "order_created")
        self.assertEqual(kwargs["properties"]["total"], 20.0)
        self.assertEqual(kwargs["properties"]["currency"], "EGP")
        for personal in ("Secret", "Real Name", "01000000000", "buyer@example.invalid"):
            self.assertNotIn(personal, json.dumps(kwargs, default=str))

    def test_paid_order_is_reported_once_even_if_the_callback_repeats(self):
        payment = self.pending_payment()
        first = self.sent(lambda: apply_transaction_result(self.paid_event(payment)))
        (name, kwargs), = first
        self.assertEqual(name, "order_paid")
        self.assertEqual(kwargs["properties"]["total"], 20.0)
        self.assertEqual(Order.objects.get(pk=payment.order_id).status, Order.PAID)
        self.assertEqual(self.sent(lambda: apply_transaction_result(self.paid_event(payment))), [])

    def test_a_wrong_amount_is_not_counted_as_paid(self):
        payment = self.pending_payment()
        events = self.sent(lambda: apply_transaction_result(self.paid_event(payment, amount_cents=1)))
        self.assertEqual(events, [])

    def test_failed_payment(self):
        payment = self.pending_payment()
        events = self.sent(lambda: apply_transaction_result(self.paid_event(payment, success=False)))
        self.assertEqual(self.names(events), ["payment_failed"])

    def test_expired_order(self):
        order = self.checkout()
        events = self.sent(lambda: cancel_if_unpaid(order.pk))
        self.assertEqual(self.names(events), ["order_expired"])
        self.assertEqual(Order.objects.get(pk=order.pk).status, Order.CANCELLED)

    def test_payment_started_then_reused(self):
        order = self.checkout()
        with patch("payments.services.create_intention", return_value=("secret-abc", "12345")):
            first = self.sent(lambda: start_payment_for_order(order.pk, self.user))
            second = self.sent(lambda: start_payment_for_order(order.pk, self.user))
        self.assertEqual([(n, k["properties"]["reused"]) for n, k in first], [("payment_started", False)])
        self.assertEqual([(n, k["properties"]["reused"]) for n, k in second], [("payment_started", True)])
        self.assertNotIn("secret-abc", json.dumps([first, second], default=str))

    def test_everything_still_works_with_analytics_off(self):
        with override_settings(POSTHOG_API_KEY=""):
            order = self.checkout()
            self.assertEqual(order.total, Decimal("20"))
            self.assertEqual(CartItem.objects.filter(user=self.user).count(), 0)
        self.client_mock.capture.assert_not_called()


class PosthogTestCommandTests(TestCase):
    @override_settings(POSTHOG_API_KEY="")
    def test_command_explains_the_missing_key(self):
        with self.assertRaisesMessage(CommandError, "POSTHOG_API_KEY is empty"):
            call_command("posthog_test")

    @override_settings(POSTHOG_API_KEY="phc_test", POSTHOG_ENVIRONMENT="test")
    def test_command_sends_and_flushes(self):
        fake = MagicMock()
        with patch("antique.analytics.get_client", return_value=fake):
            call_command("posthog_test", stdout=StringIO())
        self.assertEqual(fake.capture.call_args.args[0], "posthog_test")
        fake.flush.assert_called_once()
