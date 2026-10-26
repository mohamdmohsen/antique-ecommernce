
from django.urls import path
from .views import remove_from_cart,add_to_cart,cart_details

urlpatterns =[
    path('cart/',cart_details,name = "cart_details"),
    path('cart/add/<int:pk>/',add_to_cart, name="add_to_cart"),
    path('cart/remove/<int:pk>/',remove_from_cart, name="remove_from_cart"),
]