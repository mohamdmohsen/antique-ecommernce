from decimal import Decimal
from unittest.mock import patch

from django.contrib.staticfiles import finders
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cart.models import CartItem
from catalog.models import Product
from order.models import Order
from payments.models import Payment
from users.models import User
from .i18n import AR, EN


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class StorefrontTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('web-buyer','web@example.invalid','Synthetic-Buyer-98!',email_verified=True)
        self.product = Product.objects.create(title='Clock', title_ar='ساعة', description='<script>bad()</script>', price=Decimal('10'), stock=2, image='products/test.jpg')

    def test_root_language_preference_translation_parity_and_static_discovery(self):
        self.assertEqual(set(EN), set(AR))
        self.assertTrue(finders.find('web/shop.css'))
        self.assertTrue(finders.find('web/fonts/amiri-arabic-400-normal.woff2'))
        response = self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Clock')
        self.client.post('/preferences/', {'lang':'ar','theme':'dark','next':'/'})
        response = self.client.get('/')
        self.assertContains(response,'dir="rtl"')
        self.assertContains(response,'data-theme="dark"')
        self.assertContains(response,'ساعة')
        self.assertEqual(response['Content-Language'],'ar')

    def test_catalog_search_sort_pagination_and_escaping(self):
        for i in range(25):
            Product.objects.create(title=f'Vase {i}',price=Decimal(i+1),stock=1)
        response = self.client.get('/?search=Vase&ordering=-price')
        self.assertEqual(len(response.context['page']),24)
        self.assertEqual(response.context['page'][0].price,Decimal('25'))
        self.assertContains(response,'page=2')
        self.assertEqual(len(self.client.get('/?search=Vase&page=2').context['page']),1)
        response = self.client.get(f'/pieces/{self.product.pk}/')
        self.assertNotContains(response,'<script>bad()</script>')
        self.assertContains(response,'&lt;script&gt;')

    def test_verified_customer_can_buy_through_existing_services(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(f'/pieces/{self.product.pk}/add/', {'quantity':1}).status_code,302)
        self.assertEqual(self.client.get('/cart/').context['total'],Decimal('10'))
        response = self.client.post('/checkout/', {'full_name':'Test Buyer','phone':'1234567','address':'Test street','city':'Cairo','terms_accepted':True,'buyer_confirmed':True})
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response,reverse('web:order',args=[order.pk]))
        self.assertFalse(CartItem.objects.filter(user=self.user).exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock,1)
        with patch('payments.services.create_intention',return_value=('synthetic-secret','1234')):
            response = self.client.post(reverse('web:pay',args=[order.pk]))
        self.assertEqual(response.status_code,302)
        self.assertTrue(response['Location'].startswith('https://eg.checkout.paymob.com/'))
        self.assertEqual(Payment.objects.get(order=order).intention_state,Payment.READY)
        self.client.get('/payment-result/?success=true')
        order.refresh_from_db()
        self.assertEqual(order.status,Order.PENDING)

    def test_unverified_customer_and_ownership_are_enforced(self):
        other = User.objects.create_user('other','other@example.invalid','synthetic-only')
        order=Order.objects.create(user=other,total=10,full_name='Test',phone='0',address='Test',city='Test')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('web:order',args=[order.pk])).status_code,404)
        with patch('payments.services.create_intention') as mocked:
            self.client.post(reverse('web:pay',args=[order.pk]))
            mocked.assert_not_called()
        self.client.force_login(other)
        self.client.post(f'/pieces/{self.product.pk}/add/',{'quantity':1})
        self.assertFalse(CartItem.objects.filter(user=other).exists())
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_authentication_forms_and_redirect_safety(self):
        response=self.client.post('/sign-in/?next=https://attacker.invalid/',{'username':self.user.username,'password':'Synthetic-Buyer-98!'})
        self.assertRedirects(response,'/')
        self.assertEqual(self.client.get('/sign-out/').status_code,405)
        self.client.post('/sign-out/')
        self.assertNotIn('_auth_user_id',self.client.session)
        self.assertEqual(self.client.post('/preferences/',{'lang':'ar','next':'//attacker.invalid/'} )['Location'],'/')

    def test_registration_verification_and_reset_email_flows(self):
        response=self.client.post('/create-account/',{'username':'new-buyer','email':'new@example.invalid','password1':'A-Synthetic-Password-982!','password2':'A-Synthetic-Password-982!','age_confirmed':True,'terms_accepted':True})
        self.assertEqual(response.status_code,200)
        user=User.objects.get(username='new-buyer')
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox),1)
        self.client.post('/sign-in/',{'username':'new-buyer','password':'A-Synthetic-Password-982!'})
        self.assertNotIn('_auth_user_id',self.client.session)
        self.assertEqual(self.client.post('/forgot-password/',{'email':self.user.email}).status_code,200)
        self.assertEqual(len(mail.outbox),2)
        self.assertEqual(self.client.post('/resend-verification/',{'email':user.email}).status_code,200)
        self.assertEqual(len(mail.outbox),3)

    def test_forms_enforce_csrf_and_no_get_mutations(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(f'/pieces/{self.product.pk}/add/',{'quantity':1}).status_code,403)
        self.assertEqual(client.post('/preferences/',{'lang':'ar'}).status_code,403)
        self.assertEqual(client.post('/sign-out/').status_code,403)
        self.assertEqual(client.get(f'/pieces/{self.product.pk}/add/').status_code,405)
        self.assertEqual(client.get('/checkout/').status_code,200)
        self.assertFalse(Order.objects.exists())

    def test_html_login_has_the_same_account_limit(self):
        for i in range(11):
            response=self.client.post('/sign-in/',{'username':'missing','password':'synthetic-only'})
            self.assertEqual(response.status_code,429 if i==10 else 200)
        self.assertIn('Retry-After',response)
