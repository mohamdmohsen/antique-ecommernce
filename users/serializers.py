from rest_framework import serializers
from .models import User
from django.contrib.auth.password_validation import validate_password


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only = True, validators = [validate_password])

    class Meta:
        model  = User
        fields = ("username","email","password")
    def create(self,validated_data):
        return User.objects.create_user(**validated_data)


class UserSerializers(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id","username","email","first_name","last_name")
        read_only_fields = ("id",)