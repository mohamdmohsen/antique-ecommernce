import threading
from unittest import skipUnless
from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient
from .models import User


@skipUnless(connection.features.has_select_for_update,'Requires PostgreSQL row locking')
@override_settings(SECURE_SSL_REDIRECT=False)
class LoginConcurrencyTests(TransactionTestCase):
    def test_account_limit_is_shared_by_concurrent_requests(self):
        User.objects.create_user(username='customer',email='customer@example.invalid',password='Synthetic-Concurrent-582!',email_verified=True)
        barrier=threading.Barrier(12,timeout=10);codes=[];errors=[]
        def worker(index):
            try:
                barrier.wait()
                result=APIClient().post('/api/api/token/',{'username':'customer','password':'wrong'},format='json',REMOTE_ADDR=f'192.0.2.{index}')
                codes.append(result.status_code)
            except Exception as exc:errors.append(str(exc))
            finally:connection.close()
        threads=[threading.Thread(target=worker,args=(i,)) for i in range(12)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads));self.assertFalse(errors,errors)
        self.assertEqual(codes.count(401),10);self.assertEqual(codes.count(429),2)
