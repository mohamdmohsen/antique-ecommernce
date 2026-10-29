from django.conf import settings
from django.core.checks import Warning, register
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


@register(deploy=True)
def seller_details_check(app_configs, **kwargs):
    required = ('SHOP_LEGAL_NAME', 'SHOP_SUPPORT_EMAIL', 'SHOP_BUSINESS_ADDRESS', 'SHOP_PHONE')
    missing = [name for name in required if not getattr(settings, name, '')]
    issues = []
    if missing:
        issues.append(Warning('Public seller details are incomplete.',
            hint='Configure ' + ', '.join(missing) + ' and review the policies before accepting public orders.',
            id='web.W001'))
    if settings.SHOP_SUPPORT_EMAIL:
        try:
            validate_email(settings.SHOP_SUPPORT_EMAIL)
        except ValidationError:
            issues.append(Warning('SHOP_SUPPORT_EMAIL is not a valid email address.', id='web.W002'))
    return issues
