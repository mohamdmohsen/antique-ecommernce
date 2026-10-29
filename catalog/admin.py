from django.contrib import admin
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "title_ar", "price", "stock")
    list_filter = ("stock",)
    search_fields = ("title", "title_ar", "description")
