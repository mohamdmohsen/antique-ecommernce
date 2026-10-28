from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from order.models import Order
from users.models import User
from .models import Payment
from .services import apply_transaction_result, flag


class ConfirmationTimeTests(TestCase):
    def setUp(self):
        customer = User.objects.create_user('time-buyer', 'time@example.invalid', 'synthetic-only')
        order = Order.objects.create(user=customer, total=Decimal('100'), full_name='Test', phone='0', address='Test', city='Test')
        self.payment = Payment.objects.create(order=order, amount_cents=10000, paymob_order_id='1234')
        self.event = {'order': {'id': '1234', 'merchant_order_id': f'pay-{self.payment.pk}'}, 'id': '5678', 'success': True, 'pending': False, 'amount_cents': 10000, 'currency': 'EGP'}

    def test_only_success_sets_confirmation_time(self):
        apply_transaction_result({**self.event, 'pending': True})
        self.payment.refresh_from_db()
        self.assertIsNone(self.payment.succeeded_at)
        apply_transaction_result({**self.event, 'success': False})
        self.payment.refresh_from_db()
        self.assertIsNone(self.payment.succeeded_at)
        confirmed = timezone.now()
        with patch('django.utils.timezone.now', return_value=confirmed):
            apply_transaction_result(self.event)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.succeeded_at, confirmed)

    def test_duplicate_callbacks_notes_and_refund_do_not_move_confirmation(self):
        confirmed = timezone.now()
        with patch('django.utils.timezone.now', return_value=confirmed):
            apply_transaction_result(self.event)
        with patch('django.utils.timezone.now', return_value=confirmed + timedelta(days=1)):
            apply_transaction_result(self.event)
            self.payment.refresh_from_db()
            flag(self.payment, 'Synthetic operator note')
            self.payment.save()  # Normal admin edits also update updated_at.
            apply_transaction_result({**self.event, 'is_refunded': True})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.succeeded_at, confirmed)
        self.assertGreater(self.payment.updated_at, confirmed)


class ConfirmationTimeMigrationTests(TransactionTestCase):
    def test_existing_payment_keeps_unknown_success_time(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [node for node in latest if node[0] != 'payments'] + [('payments', '0003_refund')]
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            user = apps.get_model('users', 'User').objects.create(username='historical-time')
            order = apps.get_model('order', 'Order').objects.create(user_id=user.pk, total=100, status='paid', full_name='Historical', phone='0', address='Test', city='Test')
            payment = apps.get_model('payments', 'Payment').objects.create(order_id=order.pk, status='succeeded', amount_cents=10000)
        finally:
            MigrationExecutor(connection).migrate(latest)
        payment = Payment.objects.get(pk=payment.pk)
        self.assertIsNone(payment.succeeded_at)
        self.assertEqual(payment.status, Payment.SUCCEEDED)
        self.assertEqual(payment.amount_cents, 10000)
