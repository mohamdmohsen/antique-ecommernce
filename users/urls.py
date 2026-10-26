
from django.urls import path
from .views import register, me ,update_me
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)


urlpatterns = [
    path('register/',register,name ="register" ),
    path('me/', me , name = "me"),
    path('update_me/', update_me , name = "update_me"),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
