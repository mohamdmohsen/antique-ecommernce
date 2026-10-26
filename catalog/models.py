from django.conf import settings
from django.db import models


# Create your models here.
class Product(models.Model):
    title = models.CharField(max_length = 200 , default = '',blank = False )
    description = models.TextField( max_length = 600, default = '',blank = True )
    price = models.DecimalField( max_digits = 10 ,decimal_places = 2)
    image = models.ImageField( upload_to="products/" )
    stock = models.PositiveIntegerField(default=1)


    def __str__(self):
        return self.title





