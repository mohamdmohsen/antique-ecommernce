from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.core import signing
from django.core.mail import send_mail
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.utils import get_md5_hash_password
from django.utils.crypto import constant_time_compare
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .throttles import LoginThrottle


class VerifiedTokenSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.email_verified:
            raise AuthenticationFailed("Verify your email before signing in.")
        return data


class LoginView(TokenObtainPairView):
    serializer_class = VerifiedTokenSerializer
    throttle_classes = [LoginThrottle]


def verification_token(user):
    return signing.dumps({"user": str(user.pk), "email": user.email}, salt="email-verification")


def send_verification(user):
    url = settings.PUBLIC_BASE_URL.rstrip("/") + "/api/verify-email/?" + urlencode({"token": verification_token(user)})
    send_mail("Verify your shop email", f"Confirm your email by opening this link:\n{url}\nThis link expires in 24 hours.", settings.DEFAULT_FROM_EMAIL, [user.email])


def send_password_reset(email):
    form = PasswordResetForm({"email": email})
    if form.is_valid():
        origin = urlsplit(settings.PUBLIC_BASE_URL)
        form.save(domain_override=origin.netloc, use_https=origin.scheme == "https", from_email=settings.DEFAULT_FROM_EMAIL,
                  email_template_name="shop_accounts/password_reset_email.txt")


class VerifiedRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        token = RefreshToken(attrs["refresh"])
        user = get_user_model().objects.filter(pk=token["user_id"], email_verified=True, is_active=True).first()
        if not user:
            raise AuthenticationFailed("Verify your email before signing in.")
        if not constant_time_compare(str(token.get(api_settings.REVOKE_TOKEN_CLAIM, "")), get_md5_hash_password(user.password)):
            raise AuthenticationFailed("Sign in again with your current password.")
        return super().validate(attrs)


class RefreshView(TokenRefreshView):
    serializer_class = VerifiedRefreshSerializer
    throttle_classes = [LoginThrottle]

