import hashlib
import hmac as hmac_lib
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from cart.models import CartItem
from catalog.models import Product
from order.models import Order
from users.models import User
from .models import Payment, WebhookEvent

SECRET = "test-hmac-secret"
SHIPPING = {"full_name": "Ali Hassan", "phone": "01000000000", "address": "1 Street", "city": "Cairo"}

# Paymob's documented HMAC field order. Written out again here on purpose, so the
# tests do not simply trust the code they are checking.
FIELDS = [
    "amount_cents", "created_at", "currency", "error_occured", "has_parent_transaction", "id",
    "integration_id", "is_3d_secure", "is_auth", "is_capture", "is_refunded",
    "is_standalone_payment", "is_voided", "order.id", "owner", "pending",
    "source_data.pan", "source_data.sub_type", "source_data.type", "success",
]


def sign(obj):
    text = ""
    for field in FIELDS:
        value = obj
        for part in field.split("."):
            value = value[part]
        text += ("true" if value else "false") if isinstance(value, bool) else str(value)
    return hmac_lib.new(SECRET.encode(), text.encode(), hashlib.sha512).hexdigest()


def callback(amount_cents, paymob_order_id, reference, txn_id, success=True):
    return {
        "id": txn_id, "pending": False, "success": success, "amount_cents": amount_cents,
        "currency": "EGP", "created_at": "2026-10-25T20:00:00.123456",
        "error_occured": False, "has_parent_transaction": False, "integration_id": 123,
        "is_3d_secure": True, "is_auth": False, "is_capture": False, "is_refunded": False,
        "is_standalone_payment": True, "is_voided": False, "owner": 1,
        "order": {"id": paymob_order_id, "merchant_order_id": reference},
        "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
    }


@override_settings(PAYMOB_HMAC_SECRET=SECRET, SECURE_SSL_REDIRECT=False)
class PaymentFlowTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ali", email="ali@test.com", password="Str0ng#Pass2026")
        self.client.force_authenticate(self.user)
        self.clock = Product.objects.create(title="Clock", price=Decimal("10.00"), image="products/a.jpg", stock=10)
        self.vase = Product.objects.create(title="Vase", price=Decimal("20.00"), image="products/b.jpg", stock=10)

    # ---- helpers ----
    def make_order(self, client=None):
        client = client or self.client
        client.post(f"/api/cart/add/{self.clock.id}/", {"quantity": 2}, format="json")
        client.post(f"/api/cart/add/{self.vase.id}/", format="json")
        response = client.post("/api/order/checkout/", SHIPPING, format="json")
        return Order.objects.get(pk=response.data["id"])

    def start(self, order, secret="secret", paymob_id="7001"):
        with patch("payments.services.create_intention", return_value=(secret, paymob_id)):
            self.client.post(f"/api/payments/orders/{order.id}/pay/")
        return Payment.objects.get(order=order)

    def hook(self, obj, signature=None):
        signature = sign(obj) if signature is None else signature
        return APIClient().post(
            f"/api/payments/webhook/?hmac={signature}", {"type": "TRANSACTION", "obj": obj}, format="json"
        )

    # ---- cart and checkout ----
    def test_cart_total_is_money_not_quantity(self):
        self.client.post(f"/api/cart/add/{self.clock.id}/", {"quantity": 2}, format="json")
        self.client.post(f"/api/cart/add/{self.vase.id}/", format="json")
        response = self.client.get("/api/cart/")
        self.assertEqual(len(response.data["items"]), 2)
        self.assertEqual(Decimal(str(response.data["total"])), Decimal("40.00"))

    def test_cart_rejects_too_much_zero_and_unknown_product(self):
        self.assertEqual(self.client.post(f"/api/cart/add/{self.clock.id}/", {"quantity": 99}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"/api/cart/add/{self.clock.id}/", {"quantity": 0}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/cart/add/99999/", format="json").status_code, 404)

    def test_checkout_keeps_every_cart_line(self):
        order = self.make_order()
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.total, Decimal("40.00"))
        self.clock.refresh_from_db()
        self.vase.refresh_from_db()
        self.assertEqual((self.clock.stock, self.vase.stock), (8, 9))
        self.assertEqual(self.client.get("/api/cart/").data["items"], [])

    def test_checkout_with_empty_cart_is_rejected(self):
        self.assertEqual(self.client.post("/api/order/checkout/", SHIPPING, format="json").status_code, 400)

    def test_failed_checkout_leaves_nothing_behind(self):
        self.client.post(f"/api/cart/add/{self.clock.id}/", {"quantity": 2}, format="json")
        Product.objects.filter(pk=self.clock.pk).update(stock=1)  # someone else bought one
        response = self.client.post("/api/order/checkout/", SHIPPING, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_preserves_items_added_after_its_cart_snapshot(self):
        self.client.post(f"/api/cart/add/{self.clock.id}/", format="json")
        original = Product.objects.select_for_update

        def add_another_item(*args, **kwargs):
            CartItem.objects.create(user=self.user, product=self.vase, quantity=1)
            return original(*args, **kwargs)

        with patch("order.services.Product.objects.select_for_update", side_effect=add_another_item):
            response = self.client.post("/api/order/checkout/", SHIPPING, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.get(pk=response.data["id"]).items.count(), 1)
        self.assertEqual(list(CartItem.objects.filter(user=self.user).values_list("product_id", flat=True)), [self.vase.id])

    # ---- starting a payment ----
    def test_start_payment_saves_paymob_order_id_and_reuses_checkout(self):
        order = self.make_order()
        with patch("payments.services.create_intention", return_value=("secretA", "7001")) as mocked:
            first = self.client.post(f"/api/payments/orders/{order.id}/pay/")
            second = self.client.post(f"/api/payments/orders/{order.id}/pay/")
        self.assertEqual(mocked.call_count, 1)
        self.assertIn("clientSecret=secretA", first.data["checkout_url"])
        self.assertEqual(first.data, second.data)
        self.assertEqual(Payment.objects.get(order=order).paymob_order_id, "7001")

    def test_old_pending_payment_without_provider_id_is_preserved_for_review(self):
        order = self.make_order()
        payment = Payment.objects.create(order=order, amount_cents=4000, client_secret="old-secret")
        with patch("payments.services.create_intention") as mocked:
            response = self.client.post(f"/api/payments/orders/{order.id}/pay/")
        self.assertEqual(response.status_code, 409)
        mocked.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual((payment.client_secret, payment.paymob_order_id), ("old-secret", ""))
        self.assertTrue(payment.needs_attention)

    def test_legacy_success_is_reconciled_and_expiry_keeps_its_stock(self):
        order = self.make_order()
        payment = Payment.objects.create(order=order, amount_cents=4000, client_secret="old-secret")
        obj = callback(4000, "7001", f"pay-{payment.id}", 9010)
        self.assertEqual(self.hook(obj).status_code, 200)
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=60))

        for _ in range(2):
            call_command("cancel_expired_orders", stdout=StringIO())
        payment.refresh_from_db()
        order.refresh_from_db()
        self.clock.refresh_from_db()
        self.assertEqual((order.status, payment.status, self.clock.stock), (Order.PENDING, Payment.PENDING, 8))
        self.assertTrue(payment.needs_attention)
        self.assertEqual(payment.note.count("Existing checkout"), 1)

        for _ in range(2):
            call_command("reconcile_payment", payment.id, "7001", stdout=StringIO())
        call_command("cancel_expired_orders", stdout=StringIO())
        order.refresh_from_db()
        payment.refresh_from_db()
        self.clock.refresh_from_db()
        self.assertEqual((order.status, payment.status, self.clock.stock), (Order.PAID, Payment.SUCCEEDED, 8))
        self.assertEqual(payment.client_secret, "old-secret")
        self.assertNotIn("Duplicate payment", payment.note)

    def test_failed_legacy_checkout_also_blocks_retry_and_expiry(self):
        order = self.make_order()
        payment = Payment.objects.create(
            order=order, amount_cents=4000, client_secret="old-secret", status=Payment.FAILED
        )
        with patch("payments.services.create_intention") as mocked:
            response = self.client.post(f"/api/payments/orders/{order.id}/pay/")
        self.assertEqual(response.status_code, 409)
        mocked.assert_not_called()
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=60))
        call_command("cancel_expired_orders", stdout=StringIO())
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PENDING)
        self.assertEqual(order.payments.count(), 1)

    def test_reconciliation_ignores_forged_event_and_accepts_later_valid_callback(self):
        order = self.make_order()
        payment = Payment.objects.create(order=order, amount_cents=4000, client_secret="old-secret")
        obj = callback(4000, "7001", f"pay-{payment.id}", 9011)
        self.assertEqual(self.hook(obj, "invalid").status_code, 400)
        call_command("reconcile_payment", payment.id, "7001", stdout=StringIO())
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PENDING)
        self.assertEqual(self.hook(obj).status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAID)

    def test_reconciliation_does_not_bind_using_unsigned_reference(self):
        order = self.make_order()
        payment = Payment.objects.create(order=order, amount_cents=4000, client_secret="old-secret")
        self.hook(callback(4000, "9999", f"pay-{payment.id}", 9012))
        call_command("reconcile_payment", payment.id, "7001", stdout=StringIO())
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PENDING)

    def test_reconciliation_refuses_conflicting_or_invalid_provider_identity(self):
        order1, order2 = self.make_order(), self.make_order()
        self.start(order1, paymob_id="7001")
        other = Payment.objects.create(order=order2, amount_cents=4000, client_secret="old-secret")
        for provider_id in ("7001", "pay-1", "", "0"):
            with self.assertRaises(CommandError):
                call_command("reconcile_payment", other.id, provider_id, stdout=StringIO())
        other.refresh_from_db()
        self.assertEqual(other.paymob_order_id, "")
        call_command("reconcile_payment", other.id, "7002", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("reconcile_payment", other.id, "7003", stdout=StringIO())

    def test_other_user_cannot_pay_my_order(self):
        order = self.make_order()
        stranger = APIClient()
        stranger.force_authenticate(User.objects.create_user(username="eve", email="eve@test.com", password="Str0ng#Pass2026"))
        self.assertEqual(stranger.post(f"/api/payments/orders/{order.id}/pay/").status_code, 404)

    # ---- the webhook ----
    def test_forged_reference_cannot_pay_another_order(self):
        order1, order2 = self.make_order(), self.make_order()
        pay1 = self.start(order1, "s1", "7001")
        pay2 = self.start(order2, "s2", "7002")
        # a genuine signature for payment 1, with the unsigned reference changed to payment 2
        forged = callback(4000, "7001", f"pay-{pay2.id}", 9001)
        self.hook(forged)
        order1.refresh_from_db()
        order2.refresh_from_db()
        self.assertEqual((order1.status, order2.status), (Order.PENDING, Order.PENDING))

    def test_bad_missing_and_tampered_signatures_are_rejected(self):
        order = self.make_order()
        payment = self.start(order)
        obj = callback(4000, "7001", f"pay-{payment.id}", 9002)
        self.assertEqual(self.hook(obj, "deadbeef").status_code, 400)
        self.assertEqual(APIClient().post("/api/payments/webhook/", {"type": "TRANSACTION", "obj": obj}, format="json").status_code, 400)
        tampered = dict(obj, amount_cents=1)
        self.assertEqual(self.hook(tampered, sign(obj)).status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PENDING)
        self.assertEqual(WebhookEvent.objects.filter(hmac_valid=False).count(), 0)

    def test_valid_callback_pays_the_order_and_duplicates_are_harmless(self):
        order = self.make_order()
        payment = self.start(order)
        obj = callback(4000, "7001", f"pay-{payment.id}", 9003)
        self.assertEqual(self.hook(obj).status_code, 200)
        self.assertEqual(self.hook(obj).status_code, 200)  # delivered twice
        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, Order.PAID)
        self.assertEqual(payment.status, Payment.SUCCEEDED)
        self.assertFalse(payment.needs_attention)

    def test_wrong_amount_does_not_pay_and_is_flagged(self):
        order = self.make_order()
        payment = self.start(order)
        self.hook(callback(100, "7001", f"pay-{payment.id}", 9004))
        order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(order.status, Order.PENDING)
        self.assertTrue(payment.needs_attention)

    def test_unknown_paymob_order_is_ignored_safely(self):
        response = self.hook(callback(4000, "55555", "pay-1", 9005))
        self.assertEqual(response.status_code, 200)

    def test_declined_card_marks_payment_failed_and_a_later_success_still_works(self):
        order = self.make_order()
        payment = self.start(order)
        self.hook(callback(4000, "7001", f"pay-{payment.id}", 9006, success=False))
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.FAILED)
        # the customer retries the card on the same Paymob page and it works
        self.hook(callback(4000, "7001", f"pay-{payment.id}", 9007))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAID)

    def test_payment_after_order_was_cancelled_is_flagged_not_lost(self):
        order = self.make_order()
        payment = self.start(order)
        Order.objects.filter(pk=order.pk).update(status=Order.CANCELLED)
        self.hook(callback(4000, "7001", f"pay-{payment.id}", 9008))
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.SUCCEEDED)  # the money is recorded
        self.assertTrue(payment.needs_attention)             # and a person is told
