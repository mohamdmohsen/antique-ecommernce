from django.db import models
from django.contrib.auth.models import AbstractUser , BaseUserManager
from django.utils.translation import gettext_lazy as _
import uuid

from antique.admin_i18n import t
# Create your models here.


class User(AbstractUser):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False)
    # Same label Django gives this field on its own User, so Django's own Arabic
    # translation is used for it.
    email = models.EmailField(_("email address"), unique=True)
    # Legacy column, no longer used: the shop does not verify emails. It is kept so
    # no migration is needed; it can be dropped later.
    email_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.username

class RateLimitBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class PolicyAcceptance(models.Model):
    REGISTRATION = "registration"
    CHECKOUT = "checkout"
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="policy_acceptances", verbose_name=t("user"))
    order = models.OneToOneField("order.Order", on_delete=models.PROTECT,
        related_name="policy_acceptance", null=True, blank=True, verbose_name=t("order"))
    purpose = models.CharField(verbose_name=t("purpose"), max_length=12, choices=[(REGISTRATION, t("Registration")), (CHECKOUT, t("Checkout"))])
    policy_version = models.CharField(verbose_name=t("policy version"), max_length=32)
    age_confirmed = models.BooleanField(verbose_name=t("age confirmed"), default=False)
    buyer_capacity_confirmed = models.BooleanField(verbose_name=t("buyer capacity confirmed"), default=False)
    created_at = models.DateTimeField(verbose_name=t("created at"), auto_now_add=True)

    class Meta:
        verbose_name = t("policy acceptance")
        verbose_name_plural = t("policy acceptances")
