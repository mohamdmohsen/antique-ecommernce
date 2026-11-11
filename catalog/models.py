from django.conf import settings
from django.db import models

from antique.admin_i18n import t


# Create your models here.
class Product(models.Model):
    title = models.CharField(verbose_name=t("title (English)"), max_length = 200 , default = '',blank = False )
    description = models.TextField(verbose_name=t("description (English)"), max_length = 600, default = '',blank = True )
    price = models.DecimalField(verbose_name=t("price"), max_digits = 10 ,decimal_places = 2)
    image = models.ImageField(verbose_name=t("image"), upload_to="products/" )
    stock = models.PositiveIntegerField(verbose_name=t("stock"), default=1)
    # Optional Arabic text for the website. The English fields above stay the
    # main ones (the API and old orders use them); Arabic pages fall back to them.
    title_ar = models.CharField(verbose_name=t("title (Arabic)"), max_length=200, blank=True, default='')
    description_ar = models.TextField(verbose_name=t("description (Arabic)"), max_length=600, blank=True, default='')

    class Meta:
        verbose_name = t("product")
        verbose_name_plural = t("products")

    def __str__(self):
        return self.title

    def name_for(self, lang):
        return (self.title_ar if lang == "ar" and self.title_ar else self.title)

    def text_for(self, lang):
        return (self.description_ar if lang == "ar" and self.description_ar else self.description)
