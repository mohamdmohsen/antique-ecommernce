from django.urls import path
from . import views

app_name = 'web'
urlpatterns = [
    path('', views.shop, name='shop'),
    path('pieces/<int:pk>/', views.product, name='product'),
    path('pieces/<int:pk>/add/', views.add, name='add'),
    path('cart/', views.cart, name='cart'),
    path('cart/<int:pk>/remove/', views.remove, name='remove'),
    path('checkout/', views.checkout, name='checkout'),
    path('orders/', views.orders, name='orders'),
    path('orders/<int:pk>/', views.order_detail, name='order'),
    path('orders/<int:pk>/pay/', views.pay, name='pay'),
    path('payment-result/', views.payment_result, name='payment_result'),
    path('sign-in/', views.sign_in, name='login'),
    path('sign-out/', views.sign_out, name='logout'),
    path('create-account/', views.register, name='register'),
    path('forgot-password/', views.email_help, name='forgot'),
    path('resend-verification/', views.email_help, {'resend': True}, name='resend'),
    path('preferences/', views.preferences, name='preferences'),
]
