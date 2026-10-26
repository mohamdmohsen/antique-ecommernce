import logging

from django.contrib.auth import get_user_model
from django.core import signing
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .accounts import send_password_reset, send_verification
from .serializers import RegisterSerializer, UserSerializers
from .throttles import EmailThrottle

logger = logging.getLogger(__name__)


def deliver(callback, *args):
    try:
        callback(*args)
    except Exception:
        logger.exception("Account email delivery failed")


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailThrottle])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    deliver(send_verification, user)
    return Response({**serializer.data, "detail": "Check your email to verify your account."}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializers(request.user).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_me(request):
    previous_email = request.user.email
    serializer = UserSerializers(request.user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    if user.email != previous_email:
        user.email_verified = False
        user.save(update_fields=["email_verified"])
        deliver(send_verification, user)
    return Response(serializer.data)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailThrottle])
def password_reset(request):
    serializer = EmailSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    deliver(send_password_reset, serializer.validated_data["email"])
    return Response({"detail": "If this address has an account, password reset instructions will be sent."})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailThrottle])
def resend_verification(request):
    serializer = EmailSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = get_user_model().objects.filter(email__iexact=serializer.validated_data["email"], email_verified=False).first()
    if user:
        deliver(send_verification, user)
    return Response({"detail": "If verification is needed, an email will be sent."})


@require_http_methods(["GET", "POST"])
def verify_email(request):
    token = request.POST.get("token") if request.method == "POST" else request.GET.get("token", "")
    valid = False
    user = None
    try:
        data = signing.loads(token or "", salt="email-verification", max_age=86400)
        user = get_user_model().objects.filter(pk=data["user"], email=data["email"], email_verified=False).first()
        valid = user is not None
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        pass
    complete = request.method == "POST" and valid
    if complete:
        complete = bool(get_user_model().objects.filter(pk=user.pk, email=data["email"], email_verified=False).update(email_verified=True))
    return render(request, "shop_accounts/verify_email.html", {"token": token, "valid": valid, "complete": complete})
