"""Recorded declarations, not identity or age verification."""
from django.db import transaction
from rest_framework import serializers

from .models import PolicyAcceptance, User

POLICY_VERSION = "2026-10-29"


def require_confirmation(value):
    if value is not True:
        raise serializers.ValidationError("This confirmation is required.")


@transaction.atomic
def register_customer(*, username, email, password, age_confirmed, terms_accepted):
    require_confirmation(age_confirmed)
    require_confirmation(terms_accepted)
    user = User.objects.create_user(username=username, email=email, password=password)
    PolicyAcceptance.objects.create(user=user, purpose=PolicyAcceptance.REGISTRATION,
        policy_version=POLICY_VERSION, age_confirmed=True)
    return user
