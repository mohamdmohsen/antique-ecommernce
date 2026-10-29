from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import psycopg
import requests
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from order.models import Order
from order.services import cancel_if_unpaid
from users.models import User
from .models import Payment, WebhookEvent
from .services import PaymentStartError, start_payment_for_order


@override_settings(SECURE_SSL_REDIRECT=False)
class InitializationTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user('init-buyer', 'init@example.invalid', 'synthetic-only')
        self.order = Order.objects.create(user=self.user, total=Decimal('10'), full_name='Test', phone='0', address='Test', city='Test')

    def test_provider_runs_without_order_lock_and_only_once_while_busy(self):
        def provider(payment):
            self.assertFalse(connection.in_atomic_block)
            if connection.vendor == 'postgresql':
                db = connection.settings_dict
                with psycopg.connect(dbname=db['NAME'], user=db['USER'], host=db['HOST'], port=db['PORT'], autocommit=True) as other:
                    other.execute('SELECT id FROM order_order WHERE id=%s FOR UPDATE NOWAIT', (self.order.pk,))
            with self.assertRaises(PaymentStartError) as exc:
                start_payment_for_order(self.order.pk, self.user)
            self.assertEqual(exc.exception.code, 'busy')
            return 'synthetic-secret', '1234'
        with patch('payments.services.create_intention', side_effect=provider) as mocked:
            first = start_payment_for_order(self.order.pk, self.user)
            second = start_payment_for_order(self.order.pk, self.user)
        self.assertEqual(first, second)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(Payment.objects.get().intention_state, Payment.READY)

    def test_unknown_result_blocks_retry_and_stock_release(self):
        with patch('payments.services.create_intention', side_effect=requests.ReadTimeout('synthetic')) as mocked:
            with self.assertRaises(PaymentStartError):
                start_payment_for_order(self.order.pk, self.user)
            with self.assertRaises(PaymentStartError) as exc:
                start_payment_for_order(self.order.pk, self.user)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(exc.exception.status, 409)
        payment = Payment.objects.get()
        self.assertEqual(payment.intention_state, Payment.UNKNOWN)
        self.assertTrue(payment.needs_attention)
        self.assertFalse(cancel_if_unpaid(self.order.pk))
        call_command('reconcile_payment', payment.pk, '1234', stdout=StringIO())
        # Identity alone does not make sending another intention safe.
        with patch('payments.services.create_intention') as mocked:
            with self.assertRaises(PaymentStartError):
                start_payment_for_order(self.order.pk, self.user)
            mocked.assert_not_called()

    def test_creating_reservation_survives_expiry_and_process_crash(self):
        Payment.objects.create(order=self.order, amount_cents=1000, intention_state=Payment.CREATING)
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now()-timedelta(days=1))
        self.assertFalse(cancel_if_unpaid(self.order.pk))
        with patch('payments.services.create_intention') as mocked:
            with self.assertRaises(PaymentStartError):
                start_payment_for_order(self.order.pk, self.user)
            mocked.assert_not_called()

    def test_api_distinguishes_busy_from_required_reconciliation(self):
        payment = Payment.objects.create(order=self.order, amount_cents=1000, intention_state=Payment.CREATING)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post(f'/api/payments/orders/{self.order.pk}/pay/')
        self.assertEqual((response.status_code, response.data['code']), (409, 'busy'))
        payment.intention_state = Payment.UNKNOWN
        payment.save(update_fields=['intention_state'])
        response = client.post(f'/api/payments/orders/{self.order.pk}/pay/')
        self.assertEqual((response.status_code, response.data['code']), (409, 'needs_review'))

    def test_malformed_provider_response_blocks_new_intentions(self):
        for secret, provider_id in [('secret', 'not-an-id'), ('x'*256, '1234'), (None, '1234')]:
            order = Order.objects.create(user=self.user,total=10,full_name='Test',phone='0',address='Test',city='Test')
            with patch('payments.services.create_intention', return_value=(secret, provider_id)) as mocked:
                with self.assertRaises(PaymentStartError):
                    start_payment_for_order(order.pk, self.user)
                with self.assertRaises(PaymentStartError):
                    start_payment_for_order(order.pk, self.user)
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(Payment.objects.get(order=order).intention_state, Payment.UNKNOWN)

    def test_unknown_initialization_preserves_callback_history(self):
        Payment.objects.create(order=self.order,amount_cents=1000,intention_state=Payment.UNKNOWN)
        event = WebhookEvent.objects.create(payload={'synthetic':True},hmac_valid=True)
        WebhookEvent.objects.filter(pk=event.pk).update(created_at=timezone.now()-timedelta(days=60))
        call_command('prune_operational_data', stdout=StringIO())
        self.assertTrue(WebhookEvent.objects.filter(pk=event.pk).exists())
