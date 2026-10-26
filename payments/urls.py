from django.urls import path
from . import views

urlpatterns = [
    path("payments/orders/<int:order_id>/pay/", views.start_payment),
    path("payments/webhook/", views.paymob_webhook),
]