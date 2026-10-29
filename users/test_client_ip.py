from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .client_ip import client_ip


@override_settings(SECURE_SSL_REDIRECT=False, TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '::1/128'])
class TrustedProxyTests(TestCase):
    def test_distinct_verified_proxy_clients_have_independent_limits(self):
        client = APIClient()
        for i in range(31):
            response = client.post('/api/api/token/', {'username': f'missing{i}', 'password': 'synthetic-only'}, format='json', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP=f'198.51.100.{i+1}')
            self.assertEqual(response.status_code, 401)

    def test_untrusted_forwarding_headers_cannot_bypass_limit(self):
        client = APIClient()
        for i in range(31):
            response = client.post('/api/api/token/', {'username': f'missing{i}', 'password': 'synthetic-only'}, format='json', REMOTE_ADDR='203.0.113.10', HTTP_X_REAL_IP=f'198.51.100.{i+1}', HTTP_X_FORWARDED_FOR=f'198.51.100.{i+1}')
            self.assertEqual(response.status_code, 401 if i < 30 else 429)

    def test_invalid_chain_and_empty_peer_fall_back_to_direct_address(self):
        for header in ['', 'invalid', '198.51.100.1, 198.51.100.2']:
            self.assertEqual(client_ip({'REMOTE_ADDR': '127.0.0.1', 'HTTP_X_REAL_IP': header}), '127.0.0.1')
        self.assertEqual(client_ip({'REMOTE_ADDR': '', 'HTTP_X_REAL_IP': '198.51.100.1'}), 'unknown')
        self.assertEqual(client_ip({'REMOTE_ADDR': '::1', 'HTTP_X_REAL_IP': '2001:db8::1'}), '2001:db8::1')

    @override_settings(TRUSTED_PROXY_CIDRS=[])
    def test_proxy_trust_is_disabled_by_default(self):
        self.assertEqual(client_ip({'REMOTE_ADDR': '127.0.0.1', 'HTTP_X_REAL_IP': '198.51.100.1'}), '127.0.0.1')
