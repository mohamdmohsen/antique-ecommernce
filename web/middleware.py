from django.utils import translation

from .i18n import LANGUAGES, Strings

# JSON API and admin keep their own behaviour.
SKIP = ("/api/", "/admin/", "/static/", "/media/")

COOKIE_MAX_AGE = 60 * 60 * 24 * 365


class WebPreferences:
    """Works out the visitor's language and theme once per request.

    Language: the "lang" cookie, else the browser's Accept-Language, else English.
    Theme: the "theme" cookie ("light" or "dark"); empty means follow the device.
    Also switches Django's own messages (form errors, password rules) to that language.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith(SKIP):
            return self.get_response(request)

        lang = request.COOKIES.get("lang")
        if lang not in LANGUAGES:
            wanted = request.headers.get("Accept-Language", "").strip().lower()
            lang = "ar" if wanted.startswith("ar") else "en"
        theme = request.COOKIES.get("theme")

        request.lang = lang
        request.theme = theme if theme in ("light", "dark") else ""
        request.t = Strings(lang)

        with translation.override(lang):
            response = self.get_response(request)
        response.headers.setdefault("Content-Language", lang)
        return response
