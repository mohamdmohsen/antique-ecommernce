from django.apps import AppConfig

from antique.admin_i18n import t


class CatalogConfig(AppConfig):
    name = 'catalog'
    verbose_name = t("Catalog")  # section title on the admin home page
