import json
import logging
from io import BytesIO, StringIO
from wsgiref.util import setup_testing_defaults

import sentry_sdk
from django.core.handlers.wsgi import WSGIHandler
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from sentry_sdk.transport import Transport

from antique.glitchtip import FILTERED, init_glitchtip, scrub_event, sentry_options


@csrf_exempt  # the real WSGI path enforces CSRF; we want the view itself to run and crash
def boom(request):
    # Built in pieces so the full text never appears in this file: GlitchTip attaches
    # a few lines of source code to each report and that must not fool the test.
    local_value = "LOCALVAR-" + "LEAK"
    raise ValueError(f"kaboom {len(local_value)}")


urlpatterns = [path("boom/", boom)]


def _leak(name):
    return f"{name}-" + "LEAK"


SECRETS = {
    "hmac": _leak("HMAC"),
    "password": _leak("PASSWORD"),
    "client_secret": _leak("CLIENTSECRET"),
    "bearer": _leak("BEARER"),
    "session": _leak("SESSION"),
    "local variable": "LOCALVAR-" + "LEAK",
}


class FakeTransport(Transport):
    """Collects what would have been sent to GlitchTip instead of using the network."""

    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        event = envelope.get_event()
        if event:
            self.events.append(event)


class DisabledByDefaultTests(SimpleTestCase):
    def test_no_dsn_means_reporting_is_off(self):
        self.assertFalse(init_glitchtip("", "production"))

    def test_invalid_dsn_does_not_break_the_shop(self):
        self.assertFalse(init_glitchtip("this is not a dsn", "production"))


class ScrubEventTests(SimpleTestCase):
    def test_removes_body_cookies_and_hides_sensitive_values(self):
        event = {
            "request": {
                "data": {"password": "x"},
                "cookies": {"sessionid": "x"},
                "query_string": "hmac=abc&page=2",
                "headers": {"Authorization": "Bearer x", "Cookie": "a=b", "Accept": "text/html"},
            }
        }
        request = scrub_event(event, {})["request"]
        self.assertNotIn("data", request)
        self.assertNotIn("cookies", request)
        self.assertEqual(request["query_string"], f"hmac={FILTERED}&page=2")
        self.assertEqual(request["headers"]["Authorization"], FILTERED)
        self.assertEqual(request["headers"]["Cookie"], FILTERED)
        self.assertEqual(request["headers"]["Accept"], "text/html")


@override_settings(ROOT_URLCONF="antique.test_glitchtip")
class EndToEndTests(SimpleTestCase):
    """Real requests through Django's WSGI entry point (what gunicorn uses), with
    GlitchTip replaced by a fake transport."""

    def setUp(self):
        self.transport = FakeTransport()
        sentry_sdk.init(**sentry_options("http://publickey@glitchtip.test/1", "test", transport=self.transport))
        self.addCleanup(sentry_sdk.init)  # back to "reporting off"

    def call_app(self, path_info, query="", body=b"", host="testserver", **headers):
        environ = {}
        setup_testing_defaults(environ)
        environ.update({
            "REQUEST_METHOD": "POST",
            "PATH_INFO": path_info,
            "QUERY_STRING": query,
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": BytesIO(body),
            "HTTP_HOST": host,
            **headers,
        })
        result = {}

        def start_response(status, response_headers, exc_info=None):
            result["status"] = int(status.split()[0])

        list(WSGIHandler()(environ, start_response))
        sentry_sdk.flush()
        return result["status"]

    def test_server_error_is_reported_without_any_secret(self):
        body = json.dumps({"password": SECRETS["password"], "client_secret": SECRETS["client_secret"]}).encode()
        status = self.call_app(
            "/boom/",
            query=f"hmac={SECRETS['hmac']}&page=2",
            body=body,
            HTTP_AUTHORIZATION=f"Bearer {SECRETS['bearer']}",
            HTTP_COOKIE=f"sessionid={SECRETS['session']}",
        )
        self.assertEqual(status, 500)

        self.assertEqual(len(self.transport.events), 1)
        event = self.transport.events[0]
        self.assertEqual(event["exception"]["values"][0]["type"], "ValueError")
        self.assertEqual(event["environment"], "test")

        everything = json.dumps(event)
        for name, secret in SECRETS.items():
            self.assertNotIn(secret, everything, f"{name} leaked into the GlitchTip report")

        # useful, harmless debugging context is still there
        request = event["request"]
        self.assertTrue(request["url"].endswith("/boom/"))
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["query_string"], f"hmac={FILTERED}&page=2")
        self.assertEqual(request["headers"]["Authorization"], FILTERED)
        frames = event["exception"]["values"][0]["stacktrace"]["frames"]
        self.assertFalse(any("vars" in frame for frame in frames))

    def test_error_log_is_reported(self):
        logging.getLogger("payments").error("Paymob intention failed for payment 7")
        sentry_sdk.flush()
        messages = [e.get("logentry", {}).get("formatted") or e.get("message") for e in self.transport.events]
        self.assertIn("Paymob intention failed for payment 7", messages)

    def test_warning_log_is_not_reported(self):
        logging.getLogger("payments").warning("Callback with unknown reference")
        sentry_sdk.flush()
        self.assertEqual(self.transport.events, [])

    def test_wrong_host_header_noise_is_ignored(self):
        self.assertEqual(self.call_app("/boom/", host="evil.example"), 400)
        self.assertEqual(self.transport.events, [])

    @override_settings(GLITCHTIP_DSN="http://publickey@glitchtip.test/1")
    def test_test_command_sends_an_event(self):
        call_command("glitchtip_test", stdout=StringIO())
        sentry_sdk.flush()
        self.assertEqual(len(self.transport.events), 1)
        self.assertIn("glitchtip_test", json.dumps(self.transport.events[0]))


class TestCommandWithoutDsnTests(SimpleTestCase):
    @override_settings(GLITCHTIP_DSN="")
    def test_command_explains_the_missing_dsn(self):
        with self.assertRaisesMessage(CommandError, "GLITCHTIP_DSN is empty"):
            call_command("glitchtip_test")
