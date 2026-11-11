from django.apps import AppConfig

from antique.admin_i18n import t


class OrderConfig(AppConfig):
    name = 'order'
    verbose_name = t("Order")  # section title on the admin home page
