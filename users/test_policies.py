from unittest.mock import patch

from django.contrib import admin
from django.db import IntegrityError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from cart.models import CartItem
from catalog.models import Product
from order.models import Order
from order.services import create_order_with_policy
from users.models import PolicyAcceptance, User
from users.policies import POLICY_VERSION, register_customer

DECLARATIONS = {'terms_accepted': True, 'buyer_confirmed': True}
SHIPPING = {'full_name': 'Synthetic Buyer', 'phone': '01000000000', 'address': 'Synthetic street', 'city': 'Cairo'}


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PolicyTests(TestCase):
    def setUp(self):
        self.password = 'Synthetic-Policy-Passphrase-973!'
        self.user = User.objects.create_user('policy-buyer', 'buyer@example.invalid', self.password, email_verified=True)
        self.product = Product.objects.create(title='Clock', price='10.00', stock=2)
        CartItem.objects.create(user=self.user, product=self.product, quantity=1)
        self.api = APIClient()

    def signup_data(self):
        return {'username':'new-policy', 'email':'new-policy@example.invalid', 'password':self.password,
                'age_confirmed':True, 'terms_accepted':True}

    def test_api_signup_requires_each_declaration_before_creating_account(self):
        for field in ('age_confirmed', 'terms_accepted'):
            for value in (None, False):
                with self.subTest(field=field, value=value):
                    data = {**self.signup_data(), 'username':f'new-{field}-{value}',
                            'email':f'{field}-{value}@example.invalid'}
                    if value is None:
                        data.pop(field)
                    else:
                        data[field] = value
                    response = self.api.post('/api/register/', data, format='json', REMOTE_ADDR='192.0.2.1')
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.data)
                    self.assertEqual(User.objects.count(),1)
        self.assertFalse(PolicyAcceptance.objects.exists())

    def test_api_signup_records_server_version_without_privilege_or_age_verification(self):
        data = {**self.signup_data(), 'policy_version':'forged', 'is_superuser':True, 'email_verified':True}
        response = self.api.post('/api/register/', data, format='json')
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='new-policy')
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.email_verified)
        self.assertTrue(user.check_password(self.password))
        event = user.policy_acceptances.get()
        self.assertEqual(event.policy_version, POLICY_VERSION)
        self.assertEqual(event.purpose, PolicyAcceptance.REGISTRATION)
        self.assertTrue(event.age_confirmed)
        self.assertIsNone(event.order)
        self.assertFalse(event.buyer_capacity_confirmed)
        self.assertNotIn('password', response.data)

    def test_api_checkout_missing_or_false_confirmation_has_no_order_or_stock_effect(self):
        self.api.force_authenticate(self.user)
        for field in ('terms_accepted','buyer_confirmed'):
            for value in (None, False):
                with self.subTest(field=field, value=value):
                    data = {**SHIPPING, **DECLARATIONS}
                    if value is None:
                        data.pop(field)
                    else:
                        data[field] = value
                    response = self.api.post('/api/order/checkout/', data, format='json')
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)
        self.assertEqual(CartItem.objects.get(user=self.user).quantity, 1)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(PolicyAcceptance.objects.exists())

    def test_checkout_records_agreement_and_snapshot_atomically(self):
        self.api.force_authenticate(self.user)
        response = self.api.post('/api/order/checkout/', {**SHIPPING, **DECLARATIONS}, format='json')
        self.assertEqual(response.status_code,201)
        order = Order.objects.get(pk=response.data['id'])
        event = order.policy_acceptance
        self.assertEqual(event.user,self.user)
        self.assertEqual(event.policy_version,POLICY_VERSION)
        self.assertEqual(event.purpose,PolicyAcceptance.CHECKOUT)
        self.assertTrue(event.buyer_capacity_confirmed)
        self.assertEqual(order.items.get().quantity,1)
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())

    def test_record_failure_rolls_back_registration_and_entire_checkout(self):
        with patch('users.models.PolicyAcceptance.objects.create', side_effect=IntegrityError('synthetic failure')):
            with self.assertRaises(IntegrityError):
                register_customer(**self.signup_data())
            with self.assertRaises(IntegrityError):
                create_order_with_policy(self.user, {**SHIPPING, **DECLARATIONS})
        self.assertFalse(User.objects.filter(username='new-policy').exists())
        self.assertFalse(Order.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock,2)
        self.assertEqual(CartItem.objects.get(user=self.user).quantity,1)

    def test_records_are_not_backfilled_and_admin_cannot_edit_them(self):
        self.assertFalse(self.user.policy_acceptances.exists())
        model_admin = admin.site._registry[PolicyAcceptance]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))
        self.assertFalse(model_admin.has_delete_permission(None))
