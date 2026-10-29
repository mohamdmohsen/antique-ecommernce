import re
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.forms import UserChangeForm
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from .accounts import verification_token
from .models import User, RateLimitBucket


@override_settings(SECURE_SSL_REDIRECT=False, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', PUBLIC_BASE_URL='https://shop.example', ADMINS=[])
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

    def test_superuser_does_not_need_email_verification(self):
        User.objects.create_superuser(username='boss', email='boss@example.invalid', password=self.password)
        self.assertTrue(User.objects.get(username='boss').email_verified)
        self.assertEqual(self.login('boss').status_code, 200)

    def test_promoting_a_user_to_superuser_verifies_the_email(self):
        user = User.objects.create_user(username='later', email='later@example.invalid', password=self.password)
        user.is_superuser = True
        user.save(update_fields=['is_superuser'])
        user.refresh_from_db()
        self.assertTrue(user.email_verified)

    def test_signup_verification_is_required_and_single_use(self):
        response = self.client.post('/api/register/', {'username':'new', 'email':'new@example.invalid', 'password':self.password, 'age_confirmed':True, 'terms_accepted':True}, format='json')
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='new')
        self.assertFalse(user.email_verified)
        self.assertEqual(self.login('new').status_code, 401)
        self.assertEqual(len(mail.outbox), 1)
        token = verification_token(user)
        self.assertEqual(self.client.get('/api/verify-email/', {'token':token}).status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.email_verified)  # link scanners cannot confirm it
        self.client.post('/api/verify-email/', {'token':token})
        self.assertEqual(self.login('new').status_code, 200)
        response = self.client.post('/api/verify-email/', {'token':token})
        self.assertFalse(response.context['complete'])
        self.assertTrue(user.check_password(self.password))

    def test_invalid_expired_and_changed_email_verification_tokens(self):
        self.user.email_verified = False
        self.user.save()
        with patch('django.core.signing.time.time', return_value=1):
            expired = verification_token(self.user)
        for token in ['bad', expired]:
            response = self.client.post('/api/verify-email/', {'token':token})
            self.assertFalse(response.context['complete'])
        token = verification_token(self.user)
        self.user.email = 'changed@example.invalid'; self.user.save()
        self.assertFalse(self.client.post('/api/verify-email/', {'token':token}).context['complete'])

    def test_email_change_blocks_login_and_refresh_until_verified(self):
        refresh = self.login().data['refresh']
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.patch('/api/update_me/', {'email':'changed@example.invalid'}, format='json').status_code, 200)
        self.user.refresh_from_db(); self.assertFalse(self.user.email_verified)
        self.client.force_authenticate(None)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.client.post('/api/api/token/refresh/', {'refresh':refresh}, format='json').status_code, 401)

    def test_password_reset_complete_and_single_use(self):
        response = self.client.post('/api/password-reset/', {'email':self.user.email}, format='json', HTTP_HOST='testserver')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        url = re.search(r'https://shop.example(/api/password-reset/[^\s]+)', mail.outbox[0].body).group(1)
        confirm = self.client.get(url)
        self.assertEqual(confirm.status_code, 302)
        url = confirm.url
        response = self.client.post(url, {'new_password1':'Another-Synthetic-Passphrase-92!', 'new_password2':'Another-Synthetic-Passphrase-92!'})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db();self.assertTrue(self.user.check_password('Another-Synthetic-Passphrase-92!'))
        self.assertFalse(self.client.get(url).context['validlink'])

    def test_reset_and_resend_do_not_disclose_email_existence(self):
        for endpoint in ['password-reset', 'resend-verification']:
            first = self.client.post(f'/api/{endpoint}/', {'email':self.user.email}, format='json')
            second = self.client.post(f'/api/{endpoint}/', {'email':'absent@example.invalid'}, format='json')
            self.assertEqual(first.data, second.data)

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


    def test_customer_reset_pages_do_not_use_admin_templates(self):
        complete = self.client.get('/api/password-reset/complete/')
        self.assertContains(complete, 'Password updated')
        self.assertNotContains(complete, 'Django administration')

    def test_password_change_revokes_access_and_refresh_tokens(self):
        tokens=self.login().data
        self.user.set_password('Replacement-Synthetic-Passphrase-999!');self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+tokens['access'])
        self.assertEqual(self.client.get('/api/me/').status_code,401)
        self.client.credentials()
        self.assertEqual(self.client.post('/api/api/token/refresh/',{'refresh':tokens['refresh']},format='json').status_code,401)
        self.assertEqual(self.login(password='Replacement-Synthetic-Passphrase-999!').status_code,200)

    def test_email_change_revokes_current_access_until_verified(self):
        tokens=self.login().data
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+tokens['access'])
        self.assertEqual(self.client.patch('/api/update_me/',{'email':'new-address@example.invalid'},format='json').status_code,200)
        self.assertEqual(self.client.get('/api/me/').status_code,401)
