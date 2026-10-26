from unittest.mock import Mock, patch
from django.contrib import admin
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from order.models import Order
from users.models import User
from .models import Payment, Refund, WebhookEvent
from .paymob import refund_transaction
from .services import flag, request_full_refund
from .tests import SHIPPING, callback, sign, SECRET


@override_settings(PAYMOB_API_KEY='synthetic-api-key', PAYMOB_HMAC_SECRET=SECRET, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', ADMINS=[('Operator','operator@example.invalid')])
class RefundTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser(username='operator', email='operator@example.invalid', password='Synthetic-Operator-582!')
        self.order = Order.objects.create(user=self.actor,total='10.00',status=Order.PAID,**SHIPPING)
        self.payment = Payment.objects.create(order=self.order,status=Payment.SUCCEEDED,amount_cents=1000,paymob_order_id='7001',paymob_transaction_id='9001')

    def test_full_refund_is_recorded_and_never_sent_twice(self):
        with patch('payments.paymob.refund_transaction',return_value={'id':9002,'success':True,'pending':False,'amount_cents':1000}) as send:
            first = request_full_refund(self.payment.pk,self.actor)
            second = request_full_refund(self.payment.pk,self.actor)
        self.assertEqual(first.pk,second.pk);send.assert_called_once()
        self.assertEqual(second.status,Refund.SUCCEEDED)
        self.payment.refresh_from_db();self.assertEqual(self.payment.status,Payment.REFUNDED)
        self.assertEqual(second.requested_by,self.actor)
        self.order.refresh_from_db();self.assertEqual(self.order.status,Order.PAID)

    def test_unknown_result_prevents_retry_and_alerts(self):
        with self.captureOnCommitCallbacks(execute=True):
            with patch('payments.paymob.refund_transaction',side_effect=TimeoutError('synthetic')) as send:
                first = request_full_refund(self.payment.pk,self.actor)
                request_full_refund(self.payment.pk,self.actor)
        send.assert_called_once();self.assertEqual(first.status,Refund.UNKNOWN)
        self.payment.refresh_from_db();self.assertTrue(self.payment.needs_attention)
        self.assertTrue(any('Payment needs attention' in message.subject for message in mail.outbox))

    def test_ineligible_and_unauthorized_cannot_issue_refund(self):
        ordinary = User.objects.create_user(username='customer',email='customer@example.invalid',password='Synthetic-582!')
        with patch('payments.paymob.refund_transaction') as send:
            with self.assertRaises(ValidationError):request_full_refund(self.payment.pk,ordinary)
            self.payment.status=Payment.PENDING;self.payment.save()
            with self.assertRaises(ValidationError):request_full_refund(self.payment.pk,self.actor)
        send.assert_not_called();self.assertFalse(Refund.objects.exists())

    def test_provider_client_uses_private_auth_and_full_amount(self):
        token = Mock();token.json.return_value={'token':'synthetic-token'}
        response = Mock();response.json.return_value={'id':9002,'success':True,'pending':False,'amount_cents':1000}
        with patch('payments.paymob.requests.post',side_effect=[token,response]) as post:
            result = refund_transaction(self.payment)
        self.assertEqual(result['id'],9002)
        self.assertEqual(post.call_args_list[0].kwargs['json'],{'api_key':'synthetic-api-key'})
        self.assertEqual(post.call_args_list[1].kwargs['json'],{'auth_token':'synthetic-token','transaction_id':'9001','amount_cents':1000})

    def hook(self,obj):
        return APIClient().post('/api/payments/webhook/?hmac='+sign(obj),{'type':'TRANSACTION','obj':obj},format='json')

    def test_dashboard_refund_does_not_infer_unsigned_refunded_amount(self):
        obj=callback(1000,'7001',f'pay-{self.payment.pk}',9001);obj['is_refunded']=True
        self.assertEqual(self.hook(obj).status_code,200)
        self.assertEqual(self.hook(obj).status_code,200)
        self.payment.refresh_from_db();self.assertEqual(self.payment.status,Payment.SUCCEEDED)
        self.assertEqual(Refund.objects.get().status,Refund.UNKNOWN)
        # A delayed ordinary success must not undo the refund.
        obj['is_refunded']=False;self.hook(obj)
        self.payment.refresh_from_db();self.assertEqual(self.payment.status,Payment.SUCCEEDED)

    def test_pending_refund_completes_from_identified_signed_callback(self):
        with patch('payments.paymob.refund_transaction',return_value={'id':9002,'pending':True}):
            refund=request_full_refund(self.payment.pk,self.actor)
        self.assertEqual(refund.status,Refund.PENDING)
        obj=callback(1000,'7001',f'pay-{self.payment.pk}',9002);obj['has_parent_transaction']=True
        self.hook(obj);refund.refresh_from_db()
        self.assertEqual(refund.status,Refund.SUCCEEDED)

    def test_partial_unmatched_or_failed_refund_event_requires_review(self):
        obj=callback(500,'7001',f'pay-{self.payment.pk}',9001);obj['is_refunded']=True
        self.hook(obj)
        self.payment.refresh_from_db();self.assertEqual(self.payment.status,Payment.SUCCEEDED)
        self.assertTrue(self.payment.needs_attention);self.assertEqual(Refund.objects.get().status,Refund.UNKNOWN)

    def test_invalid_signature_never_stores_payload(self):
        for _ in range(10):
            self.assertEqual(APIClient().post('/api/payments/webhook/?hmac=invalid',{'obj':{'id':123}},format='json').status_code,400)
        self.assertFalse(WebhookEvent.objects.exists())

    def test_attention_alert_is_sent_once_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            flag(self.payment,'Synthetic attention')
            flag(self.payment,'Synthetic repeated attention')
        self.assertEqual(sum('Payment needs attention' in message.subject for message in mail.outbox),1)
        payment_admin=admin.site._registry[Payment]
        self.assertIn('needs_attention',payment_admin.list_filter)
        self.assertIn('needs_attention',payment_admin.list_display)

    def test_manual_refund_reconciliation_validates_amount_and_identity(self):
        from io import StringIO
        from django.core.management import call_command, CommandError
        Refund.objects.create(payment=self.payment, amount_cents=1000, status=Refund.UNKNOWN)
        with self.assertRaises(CommandError):
            call_command('reconcile_refund',self.payment.pk,provider_id='9002',amount_cents=500,operator=self.actor.username,stdout=StringIO())
        with patch('payments.paymob.requests.post') as send:
            call_command('reconcile_refund',self.payment.pk,provider_id='9002',amount_cents=1000,operator=self.actor.username,stdout=StringIO())
            call_command('reconcile_refund',self.payment.pk,provider_id='9002',amount_cents=1000,operator=self.actor.username,stdout=StringIO())
        send.assert_not_called()
        self.payment.refresh_from_db();self.assertEqual(self.payment.status,Payment.REFUNDED)
        self.assertEqual(Refund.objects.count(),1)
        with self.assertRaises(CommandError):
            call_command('reconcile_refund',self.payment.pk,provider_id='9999',amount_cents=1000,operator=self.actor.username,stdout=StringIO())


import threading
import time
from unittest import skipUnless
from django.db import connection
from django.test import TransactionTestCase


@skipUnless(connection.features.has_select_for_update,'Requires PostgreSQL row locking')
@override_settings(PAYMOB_API_KEY='synthetic-api-key')
class RefundConcurrencyTests(TransactionTestCase):
    def test_concurrent_refund_actions_only_send_once(self):
        actor=User.objects.create_superuser(username='operator',email='operator@example.invalid',password='Synthetic-Concurrent-582!')
        order=Order.objects.create(user=actor,total='10.00',status=Order.PAID,**SHIPPING)
        payment=Payment.objects.create(order=order,status=Payment.SUCCEEDED,amount_cents=1000,paymob_transaction_id='9001')
        barrier=threading.Barrier(2,timeout=10);results=[];errors=[]
        def worker():
            try:
                barrier.wait();results.append(request_full_refund(payment.pk,actor).pk)
            except Exception as exc:errors.append(str(exc))
            finally:connection.close()
        def delayed(payment):
            time.sleep(0.2)
            return {'id':9002,'success':True,'pending':False,'amount_cents':1000}
        with patch('payments.paymob.refund_transaction',side_effect=delayed) as send:
            threads=[threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=15)
        self.assertFalse(errors,errors);self.assertEqual(len(set(results)),1);send.assert_called_once()
        self.assertEqual(Refund.objects.get().status,Refund.SUCCEEDED)
