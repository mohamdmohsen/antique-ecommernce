from django.conf import settings
from django.db import models
from catalog.models import Product
# Create your models here.

class CartItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete = models.CASCADE, related_name="cartitem")
    product = models.ForeignKey(Product, on_delete = models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("user", "product")


    def __str__(self):
        return f"{self.user} - {self.product} x {self.quantity}"     



