from django.contrib import admin
from django.contrib.auth.forms import UserChangeForm
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from .models import User, RateLimitBucket


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', ADMINS=[])
class AccountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.password = 'Synthetic-Account-Passphrase-582!'
        self.user = User.objects.create_user(username='customer', email='customer@example.invalid', password=self.password, email_verified=True)

    def login(self, username='customer', password=None, **extra):
        return self.client.post('/api/api/token/', {'username': username, 'password': password or self.password}, format='json', **extra)

    def test_login_throttled_per_account_and_source(self):
        for _ in range(10):
            self.assertEqual(self.login(password='wrong').status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        for i in range(20):
            self.login(username=f'other-{i}', password='wrong')
        self.assertEqual(self.login(username='another', password='wrong').status_code, 429)
        self.assertLessEqual(RateLimitBucket.objects.count(), 22)

    def test_admin_login_is_limited(self):
        for _ in range(10):
            self.client.post('/admin/login/', {'username':'customer', 'password':'wrong'})
        self.assertEqual(self.client.post('/admin/login/', {'username':'customer','password':'wrong'}).status_code, 429)

    def test_superuser_can_log_in(self):
        User.objects.create_superuser(username='boss', email='boss@example.invalid', password=self.password)
        self.assertEqual(self.login('boss').status_code, 200)

    def signup(self, username='new'):
        return self.client.post('/api/register/', {'username': username, 'email': f'{username}@example.invalid', 'password': self.password,
                                                    'age_confirmed': True, 'terms_accepted': True}, format='json')

    def test_new_customer_can_log_in_immediately_and_no_email_is_sent(self):
        self.assertEqual(self.signup().status_code, 201)
        self.assertEqual(self.login('new').status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_new_customer_refresh_token_works(self):
        self.signup()
        tokens = self.login('new').data
        response = self.client.post('/api/api/token/refresh/', {'refresh': tokens['refresh']}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    def test_refresh_is_refused_for_a_disabled_account(self):
        tokens = self.login().data
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.post('/api/api/token/refresh/', {'refresh': tokens['refresh']}, format='json').status_code, 401)

    def test_email_change_keeps_the_customer_signed_in(self):
        tokens = self.login().data
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + tokens['access'])
        self.assertEqual(self.client.patch('/api/update_me/', {'email': 'changed@example.invalid'}, format='json').status_code, 200)
        self.assertEqual(self.client.get('/api/me/').status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_verification_and_password_reset_endpoints_are_gone(self):
        for path in ['/api/verify-email/', '/api/resend-verification/', '/api/password-reset/']:
            self.assertEqual(self.client.post(path, {'email': self.user.email}, format='json').status_code, 404)
        for path in ['/forgot-password/', '/resend-verification/']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_api_is_closed_by_default_and_catalogue_is_public(self):
        self.assertEqual(self.client.get('/api/me/').status_code, 401)
        self.assertEqual(self.client.get('/api/products/').status_code, 200)
        response = self.client.get('/api/products/', HTTP_ACCEPT='text/html')
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_invalid_json_shape_is_validation_error(self):
        self.assertEqual(self.client.post('/api/register/', [], format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/api/token/', [], format='json').status_code, 400)

    def test_user_admin_uses_password_hash_aware_form(self):
        user_admin = admin.site._registry[User]
        self.assertTrue(issubclass(user_admin.form, UserChangeForm))
        self.assertTrue(user_admin.form.base_fields['password'].disabled)

    def test_admin_password_change_hashes_new_password(self):
        actor=User.objects.create_superuser(username='operator',email='operator@example.invalid',password=self.password)
        self.client.force_login(actor)
        response=self.client.post(f'/admin/users/user/{self.user.pk}/password/',{'password1':'New-Synthetic-Passphrase-492!', 'password2':'New-Synthetic-Passphrase-492!'})
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-Synthetic-Passphrase-492!'))

    def test_expired_throttle_window_allows_login_again(self):
        from datetime import timedelta
        from django.utils import timezone
        for _ in range(10):self.login(password='wrong')
        self.assertEqual(self.login().status_code,429)
        RateLimitBucket.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.login().status_code,200)


    def test_password_change_revokes_access_and_refresh_tokens(self):
        tokens=self.login().data
        self.user.set_password('Replacement-Synthetic-Passphrase-999!');self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+tokens['access'])
        self.assertEqual(self.client.get('/api/me/').status_code,401)
        self.client.credentials()
        self.assertEqual(self.client.post('/api/api/token/refresh/',{'refresh':tokens['refresh']},format='json').status_code,401)
        self.assertEqual(self.login(password='Replacement-Synthetic-Passphrase-999!').status_code,200)

