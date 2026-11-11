from django import template

from antique.admin_i18n import translate

register = template.Library()


@register.simple_tag
def tr(text):
    """{% tr "English text" %} -> Arabic when the admin is in Arabic (see antique/admin_i18n.py)."""
    return translate(text)
