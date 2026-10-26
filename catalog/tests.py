from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from .models import Product


@override_settings(SECURE_SSL_REDIRECT=False)
class CatalogTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        for title,price in [('Vase','30.00'), ('Clock','10.00'), ('Chair','20.00')]:
            Product.objects.create(title=title,price=price,image='synthetic.png',stock=3)

    def test_search_sort_and_pagination(self):
        result = self.client.get('/api/products/?ordering=price&page_size=1&page=2').data
        self.assertEqual(result['count'],3)
        self.assertEqual(result['results'][0]['title'],'Chair')
        self.assertTrue(result['next']);self.assertTrue(result['previous'])
        self.assertEqual(self.client.get('/api/products/?search=clock').data['count'],1)
        self.assertEqual(self.client.get('/api/products/?search=absent').data['count'],0)

    def test_page_size_capped_and_sort_allowlisted(self):
        Product.objects.bulk_create([Product(title=f'Item {i}',price='1.00',image='synthetic.png') for i in range(110)])
        self.assertEqual(len(self.client.get('/api/products/?page_size=10000').data['results']),100)
        self.assertEqual(self.client.get('/api/products/?ordering=description').status_code,400)
        self.assertEqual(self.client.get('/api/products/?page=999').status_code,404)
