from rest_framework import serializers
from .models import User
from .policies import register_customer, require_confirmation
from django.contrib.auth.password_validation import validate_password


class RegisterSerializer(serializers.ModelSerializer):
    age_confirmed = serializers.BooleanField(write_only=True, validators=[require_confirmation])
    terms_accepted = serializers.BooleanField(write_only=True, validators=[require_confirmation])
    password = serializers.CharField(write_only = True, validators = [validate_password])

    class Meta:
        model  = User
        fields = ("username","email","password","age_confirmed","terms_accepted")
    def create(self,validated_data):
        return register_customer(**validated_data)


class UserSerializers(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id","username","email","first_name","last_name")
        read_only_fields = ("id",)