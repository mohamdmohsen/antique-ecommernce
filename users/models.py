from django.db import models
from django.contrib.auth.models import AbstractUser , BaseUserManager
import uuid
# Create your models here.


class User(AbstractUser):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False)
    email = models.EmailField(unique=True)
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
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="policy_acceptances")
    order = models.OneToOneField("order.Order", on_delete=models.PROTECT,
        related_name="policy_acceptance", null=True, blank=True)
    purpose = models.CharField(max_length=12, choices=[(REGISTRATION, "Registration"), (CHECKOUT, "Checkout")])
    policy_version = models.CharField(max_length=32)
    age_confirmed = models.BooleanField(default=False)
    buyer_capacity_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
