import hashlib
import hmac as hmac_lib
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

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


@override_settings(PAYMOB_HMAC_SECRET=SECRET)
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
        with patch("payments.views.create_intention", return_value=(secret, paymob_id)):
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

    # ---- starting a payment ----
    def test_start_payment_saves_paymob_order_id_and_reuses_checkout(self):
        order = self.make_order()
        with patch("payments.views.create_intention", return_value=("secretA", "7001")) as mocked:
            first = self.client.post(f"/api/payments/orders/{order.id}/pay/")
            second = self.client.post(f"/api/payments/orders/{order.id}/pay/")
        self.assertEqual(mocked.call_count, 1)
        self.assertIn("clientSecret=secretA", first.data["checkout_url"])
        self.assertEqual(first.data, second.data)
        self.assertEqual(Payment.objects.get(order=order).paymob_order_id, "7001")

    def test_old_pending_payment_without_provider_id_gets_a_new_checkout(self):
        order = self.make_order()
        Payment.objects.create(order=order, amount_cents=4000, client_secret="old-secret")
        payment = self.start(order, secret="new-secret", paymob_id="7002")
        self.assertEqual((payment.client_secret, payment.paymob_order_id), ("new-secret", "7002"))

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
        self.assertEqual(WebhookEvent.objects.filter(hmac_valid=False).count(), 3)

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
