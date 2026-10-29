from django.contrib.auth import get_user_model


def lock_cart(user):
    """Serialize a customer's cart writers before locking cart rows or products.

    A user row exists even when a cart is empty, unlike a cart-item row.
    Caller must be inside transaction.atomic(). Stock locks still protect buyers
    from each other; this gate protects additions/removals against checkout.
    """
    get_user_model().objects.select_for_update().only('pk').get(pk=user.pk)
