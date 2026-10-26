from types import SimpleNamespace

from django.http import HttpResponse
from .throttles import LoginThrottle


class AdminLoginProtectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path == "/admin/login/":
            throttle = LoginThrottle()
            if not throttle.allow_request(SimpleNamespace(data=request.POST, META=request.META), None):
                response = HttpResponse("Too many sign-in attempts. Please try again later.", status=429)
                response["Retry-After"] = str(max(1, int(throttle.wait())))
                return response
        return self.get_response(request)
