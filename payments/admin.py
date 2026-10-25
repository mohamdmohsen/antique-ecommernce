from django.contrib import admin
from .models import Payment, WebhookEvent

# Register your models here.
admin.site.register(Payment)
admin.site.register(WebhookEvent)