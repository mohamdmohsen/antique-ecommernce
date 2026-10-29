from django.test import TestCase, override_settings
from django.urls import reverse
from users.models import PolicyAcceptance, User
from catalog.models import Product
from cart.models import CartItem
from order.models import Order
from .legal import POLICIES

@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   SHOP_SUPPORT_EMAIL='', SHOP_LEGAL_NAME='', SHOP_BUSINESS_ADDRESS='', SHOP_PHONE='')
class PolicyPagesTests(TestCase):
    def test_bilingual_pages_footer_and_missing_contact_are_explicit(self):
        self.assertEqual(set(POLICIES['en']),set(POLICIES['ar']))
        for lang in ('en','ar'):
            self.client.cookies['lang']=lang
            for name in ('terms','privacy','returns','contact'):
                with self.subTest(lang=lang,name=name):
                    response=self.client.get(reverse('web:'+name))
                    self.assertEqual(response.status_code,200)
                    self.assertContains(response,'El sese bazzar')
                    self.assertContains(response,'dir="rtl"' if lang=='ar' else 'dir="ltr"')
                    self.assertNotContains(response,'mailto:')
                    self.assertContains(response,reverse('web:contact'))
        self.client.cookies['lang']='en'
        response=self.client.get('/contact/')
        self.assertContains(response,'Customer support email has not yet been published.')
        self.assertContains(response,'Please do not place an order')
        self.assertContains(self.client.get('/returns/'),'14-day')
        self.assertContains(self.client.get('/returns/'),'30-day')
        self.assertEqual(self.client.post('/terms/').status_code,405)

    @override_settings(SHOP_SUPPORT_EMAIL='support@example.invalid', SHOP_LEGAL_NAME='Synthetic Seller <script>',
                       SHOP_BUSINESS_ADDRESS='Synthetic address', SHOP_PHONE='00000000000')
    def test_configured_contact_is_displayed_safely(self):
        response=self.client.get('/contact/')
        self.assertContains(response,'mailto:support@example.invalid')
        self.assertContains(response,'Synthetic Seller &lt;script&gt;')
        self.assertNotContains(response,'Customer support email has not yet been published.')
        self.assertNotContains(response,'Please do not place an order until the seller identity')

    def test_html_registration_rejects_missing_age_and_records_checked_declarations(self):
        data={'username':'policy-html', 'email':'html@example.invalid','password1':'Synthetic-Account-394!',
              'password2':'Synthetic-Account-394!','terms_accepted':True}
        response=self.client.post('/create-account/',data)
        self.assertEqual(response.status_code,200)
        self.assertFalse(User.objects.filter(username='policy-html').exists())
        self.assertContains(response,reverse('web:terms'))
        self.client.post('/create-account/',{**data,'age_confirmed':True})
        user=User.objects.get(username='policy-html')
        self.assertTrue(user.policy_acceptances.get().age_confirmed)
        self.assertFalse(user.email_verified)

    def test_existing_customer_must_confirm_new_checkout_and_receipt_matches_user(self):
        user=User.objects.create_user('existing','existing@example.invalid','Synthetic-Account-394!',email_verified=True)
        product=Product.objects.create(title='Clock',price=10,stock=2)
        CartItem.objects.create(user=user,product=product,quantity=1)
        self.client.force_login(user)
        shipping={'full_name':'Test','phone':'0','address':'Test','city':'Cairo'}
        response=self.client.post('/checkout/',{**shipping,'terms_accepted':True})
        self.assertEqual(response.status_code,200)
        self.assertFalse(Order.objects.exists())
        product.refresh_from_db();self.assertEqual(product.stock,2)
        response=self.client.post('/checkout/',{**shipping,'terms_accepted':True,'buyer_confirmed':True})
        self.assertEqual(response.status_code,302)
        event=PolicyAcceptance.objects.get(purpose=PolicyAcceptance.CHECKOUT)
        self.assertEqual(event.user,user)
        self.assertEqual(event.order.user,user)

    def test_deployment_check_reports_missing_invalid_and_complete_contacts(self):
        from .checks import seller_details_check
        self.assertEqual([warning.id for warning in seller_details_check(None)], ['web.W001'])
        with self.settings(SHOP_LEGAL_NAME='Synthetic seller', SHOP_BUSINESS_ADDRESS='Synthetic street',
                           SHOP_PHONE='0000000', SHOP_SUPPORT_EMAIL='invalid'):
            self.assertEqual([warning.id for warning in seller_details_check(None)], ['web.W002'])
        with self.settings(SHOP_LEGAL_NAME='Synthetic seller', SHOP_BUSINESS_ADDRESS='Synthetic street',
                           SHOP_PHONE='0000000', SHOP_SUPPORT_EMAIL='support@example.invalid'):
            self.assertEqual(seller_details_check(None), [])
