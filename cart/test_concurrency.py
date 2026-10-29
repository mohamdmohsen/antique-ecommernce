import threading
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from catalog.models import Product
from users.models import User
from .models import CartItem


@skipUnless(connection.features.has_select_for_update, 'requires PostgreSQL row locking')
@override_settings(SECURE_SSL_REDIRECT=False)
class CartWriteConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user('cart-race', 'cart-race@example.invalid', 'synthetic-only')
        self.product = Product.objects.create(title='Clock', price=Decimal('10'), stock=10, image='products/test.jpg')

    def run_jobs(self, jobs):
        results = {}
        def worker(name, job):
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='5s'")
                results[name] = job()
            except Exception as exc:
                results[name] = repr(exc)
            finally:
                connection.close()
        threads = [threading.Thread(target=worker, args=(name, job), name=name) for name, job in jobs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertTrue(all(not thread.is_alive() for thread in threads), results)
        return results

    def api_client(self):
        client = APIClient()
        client.force_authenticate(self.user)
        return client

    def test_add_overlaps_checkout_without_deadlock_or_readding_purchased_quantity(self):
        CartItem.objects.create(user=self.user, product=self.product, quantity=2)
        checkout_at_product = threading.Event()
        release_checkout = threading.Event()
        add_at_save = threading.Event()
        add_started = threading.Event()
        original_lock = Product.objects.select_for_update
        original_save = CartItem.save
        def product_lock(*args, **kwargs):
            if threading.current_thread().name == 'checkout':
                checkout_at_product.set()
                if not release_checkout.wait(5):
                    raise RuntimeError('checkout not released')
            return original_lock(*args, **kwargs)
        def save(item, *args, **kwargs):
            if threading.current_thread().name == 'add':
                add_at_save.set()
            return original_save(item, *args, **kwargs)
        def checkout():
            return self.api_client().post('/api/order/checkout/', {'full_name':'Test Buyer','phone':'0','address':'Test','city':'Test','terms_accepted':True,'buyer_confirmed':True}, format='json').status_code
        def add():
            if not checkout_at_product.wait(5):
                raise RuntimeError('checkout never started')
            add_started.set()
            return self.api_client().post(f'/api/cart/add/{self.product.pk}/', {'quantity':1}, format='json').status_code
        def release():
            if not add_started.wait(5):
                raise RuntimeError('add never started')
            # Before the fix, add reaches save holding Product, creating a cycle.
            # After the fix it waits on the customer gate, before Product or cart.
            add_at_save.wait(0.5)
            release_checkout.set()
            return 'released'
        with patch.object(Product.objects, 'select_for_update', side_effect=product_lock), patch.object(CartItem, 'save', save):
            results = self.run_jobs([('checkout', checkout), ('add', add), ('release', release)])
        self.assertEqual(results, {'checkout':201, 'add':201, 'release':'released'})
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)
        self.assertEqual(CartItem.objects.get(user=self.user).quantity, 1)
        self.assertEqual(self.user.orders.get().items.get().quantity, 2)

    def test_two_additions_preserve_both_quantities(self):
        barrier = threading.Barrier(2)
        def add():
            barrier.wait(5)
            return self.api_client().post(f'/api/cart/add/{self.product.pk}/', {'quantity':1}, format='json').status_code
        self.assertEqual(self.run_jobs([('first',add),('second',add)]), {'first':201,'second':201})
        self.assertEqual(CartItem.objects.get(user=self.user).quantity, 2)
