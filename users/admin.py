from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class ShopUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Email ownership", {"fields": ("email_verified",)}),)
    readonly_fields = ("email_verified",)
