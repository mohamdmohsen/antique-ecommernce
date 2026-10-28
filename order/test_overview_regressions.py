from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from payments.models import Payment, Refund
from payments.services import apply_transaction_result
from order.models import Order
from order.services import transition_order
from users.models import User

@override_settings(SECURE_SSL_REDIRECT=False)
class OverviewContractProbes(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('review-owner', 'owner@example.invalid', 'synthetic-review-only')
        self.customer = User.objects.create_user('review-buyer', 'buyer@example.invalid', 'synthetic-review-only')
        self.client.force_login(self.owner)

    def make_payment(self, status=Order.PAID, payment_status=Payment.SUCCEEDED):
        order = Order.objects.create(user=self.customer, status=status, total=Decimal('100.00'), full_name='Synthetic Buyer', phone='0', address='Synthetic', city='Synthetic', tracking_number='SYNTHETIC-TRACKING')
        payment = Payment.objects.create(order=order, status=payment_status, amount_cents=10000, paymob_order_id='1234')
        return order, payment

    def test_pending_refund_is_not_counted_as_ready_to_ship(self):
        order, payment = self.make_payment()
        Refund.objects.create(payment=payment, amount_cents=10000, status=Refund.PENDING, provider_id='5678')
        with self.assertRaisesMessage(ValidationError, 'Resolve the refund'):
            transition_order(order.pk, Order.SHIPPED, self.owner)
        context = self.client.get(reverse('admin_overview')).context
        self.assertEqual(context['awaiting_shipping'], 0, 'A refund-blocked order is included in To ship')

    def test_success_after_midnight_is_shown_on_payment_day(self):
        order, payment = self.make_payment(status=Order.PENDING, payment_status=Payment.PENDING)
        # Egypt is UTC+2 on this winter date: checkout 23:50 yesterday, paid 00:10 today.
        settled = datetime(2026, 1, 15, 22, 10, tzinfo=dt_timezone.utc)
        Payment.objects.filter(pk=payment.pk).update(created_at=settled-timedelta(minutes=20))
        with patch('django.utils.timezone.now', return_value=settled):
            apply_transaction_result({'order': {'id': '1234', 'merchant_order_id': f'pay-{payment.pk}'}, 'id': '5678', 'success': True, 'pending': False, 'amount_cents': 10000, 'currency': 'EGP'})
            order.refresh_from_db()
            self.assertEqual(order.status, Order.PAID)
            context = self.client.get(reverse('admin_overview')).context
        self.assertEqual(context['revenue'], Decimal('100'))
        self.assertEqual(context['chart'][-1]['amount'], Decimal('100'), 'Payment accepted today is assigned to checkout day instead')

    def test_shipping_link_shows_the_same_orders_as_the_counter(self):
        eligible, _ = self.make_payment()
        for refund_status in (Refund.PENDING, Refund.UNKNOWN, Refund.SUCCEEDED):
            order, payment = self.make_payment()
            Refund.objects.create(payment=payment, amount_cents=10000, status=refund_status)
        # Also exclude fully refunded payments without a ledger (legacy data).
        self.make_payment(payment_status=Payment.REFUNDED)
        _, mismatch = self.make_payment()
        mismatch.amount_cents = 5000
        mismatch.save(update_fields=['amount_cents'])
        # Any refund on an order blocks shipment, even if another payment succeeded.
        order, _ = self.make_payment()
        other = Payment.objects.create(order=order, status=Payment.FAILED, amount_cents=10000)
        Refund.objects.create(payment=other, amount_cents=10000, status=Refund.UNKNOWN)
        self.make_payment(status=Order.SHIPPED)
        response = self.client.get(reverse('admin_overview'))
        self.assertEqual(response.context['awaiting_shipping'], 1)
        list_url = reverse('admin:order_order_changelist') + '?awaiting_shipping=yes'
        self.assertContains(response, list_url)
        result = self.client.get(list_url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(list(result.context['cl'].queryset.values_list('pk', flat=True)), [eligible.pk])

    def test_undated_historical_sales_are_explained_without_inventing_dates(self):
        self.make_payment()
        response = self.client.get(reverse('admin_overview'))
        self.assertEqual(response.context['revenue'], Decimal('100'))
        self.assertEqual(response.context['paid_orders'], 1)
        self.assertEqual(response.context['period_total'], Decimal('0'))
        self.assertEqual(response.context['undated_sales'], 1)
        self.assertContains(response, 'excluded from this chart')

    def test_fractional_price_order_is_in_shipping_queue(self):
        order, payment = self.make_payment()
        order.total = Decimal('0.29')
        order.save(update_fields=['total'])
        payment.amount_cents = 29
        payment.save(update_fields=['amount_cents'])
        response = self.client.get(reverse('admin_overview'))
        self.assertEqual(response.context['awaiting_shipping'], 1)
