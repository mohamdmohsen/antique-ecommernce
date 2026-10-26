from io import StringIO
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from payments.models import Payment, Refund
from users.models import User
from .models import Order, OrderStatusEvent
from .services import transition_order
from payments.tests import SHIPPING


@override_settings(SECURE_SSL_REDIRECT=False)
class FulfillmentTests(TestCase):
    def setUp(self):
        self.actor=User.objects.create_superuser(username='operator',email='operator@example.invalid',password='Synthetic-Operator-582!')
        self.order=Order.objects.create(user=self.actor,total='10.00',**SHIPPING)

    def test_only_paid_shipping_delivery_sequence_is_allowed(self):
        with self.assertRaises(ValidationError):transition_order(self.order.pk,Order.DELIVERED,self.actor)
        self.order.status=Order.PAID;self.order.save()
        with self.assertRaises(ValidationError):transition_order(self.order.pk,Order.SHIPPED,self.actor)
        Payment.objects.create(order=self.order,status=Payment.SUCCEEDED,amount_cents=1000)
        with self.assertRaises(ValidationError):transition_order(self.order.pk,Order.SHIPPED,self.actor)
        self.order.tracking_number='SYNTHETIC-TRACK';self.order.save()
        transition_order(self.order.pk,Order.SHIPPED,self.actor)
        transition_order(self.order.pk,Order.DELIVERED,self.actor)
        self.assertEqual(OrderStatusEvent.objects.count(),2)
        self.assertEqual(OrderStatusEvent.objects.first().actor,self.actor)
        with self.assertRaises(ValidationError):transition_order(self.order.pk,Order.PENDING,self.actor)

    def test_refund_blocks_fulfillment(self):
        self.order.status=Order.PAID;self.order.tracking_number='TRACK';self.order.save()
        payment=Payment.objects.create(order=self.order,status=Payment.SUCCEEDED,amount_cents=1000)
        Refund.objects.create(payment=payment,amount_cents=1000)
        with self.assertRaises(ValidationError):transition_order(self.order.pk,Order.SHIPPED,self.actor)

    def test_admin_cannot_change_status_or_total_with_forged_fields(self):
        client=APIClient();client.force_login(self.actor)
        response=client.post(f'/admin/order/order/{self.order.pk}/change/',{**SHIPPING,'status':Order.DELIVERED,'total':'0.01','tracking_number':'TRACK','_save':'Save'})
        self.assertEqual(response.status_code,302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status,Order.PENDING)
        self.assertEqual(str(self.order.total),'10.00')


class BackupTests(TransactionTestCase):
    def test_backup_is_private_and_readable(self):
        User.objects.create_user(username='backup-user',email='backup@example.invalid',password='Synthetic-Backup-582!')
        with TemporaryDirectory() as directory:
            output=StringIO();call_command('backup_database',directory=directory,stdout=output)
            path=Path(output.getvalue().strip())
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertGreater(path.stat().st_size,0)
            if connection.vendor=='sqlite':
                restored=sqlite3.connect(str(path))
                try:
                    self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                    self.assertEqual(restored.execute('SELECT username FROM users_user').fetchone()[0],'backup-user')
                finally:restored.close()
            else:
                result=subprocess.run(['pg_restore','--list',str(path)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0)
                self.assertIn('users_user',result.stdout)
