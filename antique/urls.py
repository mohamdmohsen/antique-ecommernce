"""
URL configuration for antique project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve

from order.dashboard import overview


urlpatterns =[
    # must come before admin/ so that admin/overview/ is not swallowed by it
    path('admin/overview/', admin.site.admin_view(overview), name='admin_overview'),
    path('admin/', admin.site.urls),
    path('', include('web.urls')),
    path('api/',include("users.urls")),
    path('api/',include("catalog.urls")),
    path('api/',include("cart.urls")),
    path('api/',include("order.urls")),
    path('api/',include("payments.urls")),

    
]
# Product photos. Django's static() helper serves nothing when DEBUG=False, so the
# images would disappear in production; this serves them in both modes. It is fine
# for a small shop's photos; for heavy traffic put a CDN or Nginx in front of /media/.
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]