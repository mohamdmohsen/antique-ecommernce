from django.db import transaction

from catalog.models import Product
from .models import CartItem


class CartError(Exception):
    """Something the customer can fix. `code` is stable; `message` is for the API."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def add_item(user, product_id, quantity):
    """Add `quantity` of a product to the user's cart, never above the stock.

    The product row is locked while we work, so a double click (or two tabs)
    cannot create two cart rows or push the quantity above the stock.
    """
    with transaction.atomic():
        try:
            product = Product.objects.select_for_update().get(pk=product_id)
        except Product.DoesNotExist:
            raise CartError("not_found", "Product not found")

        item = CartItem.objects.filter(user=user, product=product).first()
        new_quantity = (item.quantity if item else 0) + quantity

        if new_quantity > product.stock:
            raise CartError("stock", "Not enough stock")

        if item:
            item.quantity = new_quantity
            item.save(update_fields=["quantity"])
        else:
            CartItem.objects.create(user=user, product=product, quantity=new_quantity)
