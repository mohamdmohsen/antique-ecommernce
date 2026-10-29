from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from cart.models import CartItem
from users.policies import POLICY_VERSION


def site(request):
    """Variables every page needs. Returns nothing for admin and JSON API pages."""
    lang = getattr(request, "lang", None)
    if lang is None:
        return {}

    user = getattr(request, "user", None)
    cart_count = 0
    if user is not None and user.is_authenticated:
        cart_count = CartItem.objects.filter(user=user).aggregate(n=Sum("quantity"))["n"] or 0

    return {
        "policy_version": POLICY_VERSION,
        "support_email": settings.SHOP_SUPPORT_EMAIL,
        "seller_name": settings.SHOP_LEGAL_NAME,
        "seller_address": settings.SHOP_BUSINESS_ADDRESS,
        "seller_phone": settings.SHOP_PHONE,
        "seller_registration": settings.SHOP_REGISTRATION_DETAILS,
        "seller_details_complete": all((settings.SHOP_SUPPORT_EMAIL, settings.SHOP_LEGAL_NAME,
            settings.SHOP_BUSINESS_ADDRESS, settings.SHOP_PHONE)),
        "lang": lang,
        "dir": "rtl" if lang == "ar" else "ltr",
        "other_lang": "en" if lang == "ar" else "ar",
        "theme": request.theme,
        "t": request.t,
        "cart_count": cart_count,
        "current_path": request.get_full_path(),
        "payment_window": settings.ORDER_PAYMENT_WINDOW_MINUTES,
        "year": timezone.now().year,
    }
