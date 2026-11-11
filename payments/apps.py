from django.apps import AppConfig

from antique.admin_i18n import t


class PaymentsConfig(AppConfig):
    name = 'payments'
    verbose_name = t("Payments")  # section title on the admin home page
