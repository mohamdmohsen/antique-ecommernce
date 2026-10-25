
from django.urls import path
from .views import product_details,product_list

urlpatterns =[
    path('products/',product_list,name = "product_list"),
    path('products/<int:pk>/',product_details, name="product_details")
]
