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
    email_verified = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # A superuser is created by the shop owner, so there is no email to confirm.
        if self.is_superuser and not self.email_verified:
            self.email_verified = True
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "email_verified"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.username

class RateLimitBucket(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
