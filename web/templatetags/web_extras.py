from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """1200 -> '1,200.00' in both languages (Django's own number format would
    change the separators in Arabic and confuse prices)."""
    try:
        return f"{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.filter
def ref_number(pk):
    """Inventory number shown on every piece, like a museum label: 42 -> '0042'."""
    return f"{int(pk):04d}"


@register.filter
def pname(product, lang):
    return product.name_for(lang)


@register.filter
def ptext(product, lang):
    return product.text_for(lang)


@register.filter
def status_text(status, t):
    return t[f"st_{status}"]


@register.simple_tag
def line_total(price, quantity):
    return Decimal(price) * int(quantity)
