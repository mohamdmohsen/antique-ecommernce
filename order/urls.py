from django.urls import path
from . import views

urlpatterns = [
    path("order", views.order_list),
    path("order/checkout/", views.checkout),
    path("order/<int:pk>/", views.order_detail),
]