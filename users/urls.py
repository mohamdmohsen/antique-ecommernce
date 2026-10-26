from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .accounts import LoginView, RefreshView

urlpatterns = [
    path("register/", views.register, name="register"),
    path("me/", views.me, name="me"),
    path("update_me/", views.update_me, name="update_me"),
    path("api/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", RefreshView.as_view(), name="token_refresh"),
    path("password-reset/", views.password_reset, name="password_reset"),
    path("password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="shop_accounts/password_reset_confirm.html", success_url=reverse_lazy("password_reset_complete")), name="password_reset_confirm"),
    path("password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="shop_accounts/password_reset_complete.html"), name="password_reset_complete"),
    path("resend-verification/", views.resend_verification, name="resend_verification"),
    path("verify-email/", views.verify_email, name="verify_email"),
]
