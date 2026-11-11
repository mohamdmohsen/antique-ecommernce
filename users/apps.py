from django.apps import AppConfig

from antique.admin_i18n import t


class UsersConfig(AppConfig):
    name = 'users'
    verbose_name = t("Users")  # section title on the admin home page
