from django.contrib.auth import get_user_model
from django.utils.crypto import constant_time_compare
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .throttles import LoginThrottle


class LoginView(TokenObtainPairView):
    throttle_classes = [LoginThrottle]


class RefreshSerializer(TokenRefreshSerializer):
    """Refuses a refresh token once the account is disabled or the password changed."""

    def validate(self, attrs):
        token = RefreshToken(attrs["refresh"])
        user = get_user_model().objects.filter(pk=token["user_id"], is_active=True).first()
        if not user:
            raise AuthenticationFailed("Sign in again.")
        if not constant_time_compare(str(token.get(api_settings.REVOKE_TOKEN_CLAIM, "")), get_md5_hash_password(user.password)):
            raise AuthenticationFailed("Sign in again with your current password.")
        return super().validate(attrs)


class RefreshView(TokenRefreshView):
    serializer_class = RefreshSerializer
    throttle_classes = [LoginThrottle]
