from django.urls import path

from . import views
from .accounts import LoginView, RefreshView

urlpatterns = [
    path("register/", views.register, name="register"),
    path("me/", views.me, name="me"),
    path("update_me/", views.update_me, name="update_me"),
    path("api/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", RefreshView.as_view(), name="token_refresh"),
]
