from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import PolicyAcceptance, User


@admin.register(User)
class ShopUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Email ownership", {"fields": ("email_verified",)}),)
    readonly_fields = ("email_verified",)


@admin.register(PolicyAcceptance)
class PolicyAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "order", "policy_version", "created_at")
    list_filter = ("purpose", "policy_version")
    readonly_fields = tuple(field.name for field in PolicyAcceptance._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
