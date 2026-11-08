from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from order.models import Order
from order.services import cancel_if_unpaid
from users.models import User
from web.i18n import AR, EN
from .models import Payment
from .services import PaymentStartError, provider_rejected, start_payment_for_order


def http_error(status, body='{"detail": "synthetic"}'):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode()
    return requests.HTTPError(f"{status} error", response=response)


def refused_connection(*args, **kwargs):
    """A REAL refused connection (nothing listens on port 1), not a hand-made exception."""
    session = requests.Session()
    session.trust_env = False  # ignore any proxy settings of the machine running the tests
    return session.post("http://127.0.0.1:1/", timeout=2)


@override_settings(SECURE_SSL_REDIRECT=False)
class RejectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reject-buyer', 'reject@example.invalid', 'synthetic-only')
        self.order = Order.objects.create(user=self.user, total=Decimal('10'), full_name='Test', phone='0', address='Test', city='Test')

    def pay(self, **provider):
        with patch('payments.services.create_intention', **provider) as mocked:
            try:
                return start_payment_for_order(self.order.pk, self.user), mocked
            except PaymentStartError as exc:
                return exc, mocked

    def test_rejected_request_leaves_the_order_payable(self):
        # What a wrong integration id (404), a bad secret key (401) or a missing field (400) look like.
        for status in (400, 401, 403, 404):
            result, _ = self.pay(side_effect=http_error(status, '{"detail": "Integration not found"}'))
            self.assertIsInstance(result, PaymentStartError)
            self.assertEqual((result.code, result.status), ('provider_rejected', 502))
            payment = Payment.objects.filter(order=self.order).latest('pk')
            self.assertEqual((payment.status, payment.intention_state, payment.needs_attention),
                             (Payment.FAILED, Payment.NEW, False))
            self.assertIn(f'HTTP {status}', payment.note)
            self.assertIn('Integration not found', payment.note)  # the real cause is visible
            self.assertEqual(Order.objects.get(pk=self.order.pk).status, Order.PENDING)

    def test_customer_can_pay_after_the_problem_is_fixed(self):
        self.pay(side_effect=http_error(400))
        url, mocked = self.pay(return_value=('secret-abc', '12345'))
        self.assertIn('clientSecret=secret-abc', url)
        self.assertEqual(Payment.objects.filter(order=self.order).count(), 2)
        self.assertEqual(Payment.objects.filter(order=self.order, status=Payment.PENDING).count(), 1)

    def test_uncertain_failures_still_block_a_second_payment(self):
        for number, failure in enumerate([http_error(500), http_error(502), http_error(408),
                                          requests.ReadTimeout('synthetic'), KeyError('client_secret')]):
            order = Order.objects.create(user=self.user, total=10, full_name='T', phone='0', address='T', city='T')
            with patch('payments.services.create_intention', side_effect=failure) as mocked:
                for _ in range(2):
                    with self.assertRaises(PaymentStartError) as caught:
                        start_payment_for_order(order.pk, self.user)
                    self.assertEqual(caught.exception.code, 'needs_review')
            self.assertEqual(mocked.call_count, 1, f'{failure!r} allowed a second provider call')
            self.assertEqual(Payment.objects.get(order=order).intention_state, Payment.UNKNOWN)

    def test_classification(self):
        self.assertTrue(provider_rejected(http_error(400)))
        self.assertTrue(provider_rejected(http_error(429)))
        self.assertFalse(provider_rejected(http_error(408)))
        self.assertFalse(provider_rejected(http_error(500)))
        self.assertTrue(provider_rejected(requests.ConnectTimeout()))
        self.assertFalse(provider_rejected(requests.ReadTimeout()))
        self.assertFalse(provider_rejected(ValueError('x')))
        self.assertFalse(provider_rejected(requests.HTTPError('no response attached')))

    def test_server_without_internet_does_not_lock_the_order(self):
        result, _ = self.pay(side_effect=refused_connection)
        self.assertEqual(result.code, 'provider_rejected')
        payment = Payment.objects.get(order=self.order)
        self.assertEqual((payment.status, payment.intention_state), (Payment.FAILED, Payment.NEW))
        self.assertIn('Could not reach Paymob', payment.note)

    def test_website_shows_a_retry_message_not_the_contact_us_warning(self):
        self.client.force_login(self.user)
        with patch('payments.services.create_intention', side_effect=http_error(400)):
            response = self.client.post(reverse('web:pay', args=[self.order.pk]), follow=True)
        self.assertContains(response, 'could not start this payment')
        self.assertNotContains(response, 'checking an earlier payment')

    def test_message_exists_in_both_languages(self):
        for texts in (EN, AR):
            self.assertTrue(texts['pay_err_provider_rejected'].strip())


@override_settings(SECURE_SSL_REDIRECT=False)
class ReleaseCommandTests(TestCase):
    """Recovery for orders that were locked before this fix (or by a real unknown outcome)."""

    def setUp(self):
        user = User.objects.create_user('release-buyer', 'release@example.invalid', 'synthetic-only')
        self.order = Order.objects.create(user=user, total=Decimal('10'), full_name='T', phone='0', address='T', city='T')
        self.payment = Payment.objects.create(order=self.order, amount_cents=1000, needs_attention=True,
                                              intention_state=Payment.UNKNOWN, note='locked earlier')
        self.user = user

    def release(self, *extra):
        call_command('release_unconfirmed_payment', str(self.payment.pk), *extra, stdout=StringIO())

    def test_requires_the_operator_to_confirm_they_checked_paymob(self):
        with self.assertRaisesMessage(CommandError, '--confirmed-not-created'):
            self.release()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.intention_state, Payment.UNKNOWN)

    def test_unlocks_the_order_so_the_customer_can_pay_and_expiry_can_clean_up(self):
        self.release('--confirmed-not-created')
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.intention_state, self.payment.needs_attention),
                         (Payment.FAILED, Payment.NEW, False))
        self.assertIn('Released by an operator', self.payment.note)
        with patch('payments.services.create_intention', return_value=('secret-xyz', '999')):
            self.assertIn('clientSecret=secret-xyz', start_payment_for_order(self.order.pk, self.user))
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now() - timedelta(days=1))
        Payment.objects.filter(order=self.order, status=Payment.PENDING).update(status=Payment.FAILED)
        self.assertTrue(cancel_if_unpaid(self.order.pk))

    def test_refuses_when_paymob_may_hold_a_real_checkout(self):
        empty = {'client_secret': '', 'paymob_order_id': '', 'paymob_transaction_id': None}
        for field, value in [('client_secret', 'abc'), ('paymob_order_id', '123'), ('paymob_transaction_id', '77')]:
            Payment.objects.filter(pk=self.payment.pk).update(**{field: value})
            with self.assertRaisesMessage(CommandError, 'Paymob already knows'):
                self.release('--confirmed-not-created')
            Payment.objects.filter(pk=self.payment.pk).update(**{field: empty[field]})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.intention_state, Payment.UNKNOWN)

    def test_refuses_a_payment_that_needs_no_release(self):
        Payment.objects.filter(pk=self.payment.pk).update(intention_state=Payment.READY, paymob_order_id='5')
        with self.assertRaises(CommandError):
            self.release('--confirmed-not-created')
