"""Tests for the English / Arabic admin dashboard.

Two kinds of test:
  * Coverage: every label written as t("...") or {% tr "..." %} has an Arabic entry in
    antique/admin_i18n.py, and every Arabic entry is really used. So a new label can
    never be shown in English only by accident.
  * Pages: the real admin screens render in both languages (direction, words, numbers),
    the language button works, and the JSON API is not affected.
"""
import ast
import re
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.contrib import admin
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import formats, timezone, translation

from antique.admin_i18n import AR, translate
from catalog.models import Product
from order.models import Order
from payments.models import Payment
from users.models import User

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "venv", "migrations", "node_modules", "staticfiles", "__pycache__", ".git"}


def project_files(suffix):
    for path in ROOT.rglob(f"*{suffix}"):
        if not SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


def texts_used_in_python():
    """Every literal string passed to t("...") in the project's code (not in tests)."""
    found = set()
    for path in project_files(".py"):
        if path.name.startswith("test"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "t" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def texts_used_in_templates():
    """Every literal string in {% tr "..." %} / {% tr '...' %}."""
    found = set()
    pattern = re.compile(r"""\{%\s*tr\s+(?:"([^"]*)"|'([^']*)')\s*%\}""")
    for path in project_files(".html"):
        for double, single in pattern.findall(path.read_text(encoding="utf-8")):
            found.add(double or single)
    return found


class TranslationCoverageTests(SimpleTestCase):
    def test_every_label_in_the_code_has_an_arabic_entry(self):
        used = texts_used_in_python() | texts_used_in_templates()
        self.assertTrue(used, "the scan found no labels at all; the test itself is broken")
        self.assertEqual(sorted(used - set(AR)), [], "add these to AR in antique/admin_i18n.py")

    def test_no_unused_arabic_entries(self):
        used = texts_used_in_python() | texts_used_in_templates()
        self.assertEqual(sorted(set(AR) - used), [], "remove these from AR (nothing uses them)")

    def test_arabic_entries_are_real_translations(self):
        for english, arabic in AR.items():
            with self.subTest(english):
                self.assertTrue(arabic.strip())
                self.assertNotEqual(arabic, english)
                # placeholders like %(id)s must survive the translation
                self.assertEqual(sorted(re.findall(r"%\(\w+\)s", english)),
                                 sorted(re.findall(r"%\(\w+\)s", arabic)))

    def test_every_admin_model_label_changes_in_arabic(self):
        """Model names, field names and status choices of every model shown in the admin."""
        ours = {"catalog", "order", "payments", "users"}
        legacy_unshown = {("users", "User", "email_verified")}
        checked = 0
        for model in admin.site._registry:
            meta = model._meta
            if meta.app_label not in ours:
                continue
            labels = {"verbose_name": meta.verbose_name, "verbose_name_plural": meta.verbose_name_plural}
            for field in meta.get_fields():
                if (not getattr(field, "concrete", False) or field.auto_created
                        or field.name == "id" or (meta.app_label, meta.object_name, field.name) in legacy_unshown):
                    continue
                if meta.object_name == "User":  # the rest of User comes from Django, already translated
                    continue
                labels[f"field {field.name}"] = field.verbose_name
                for value, label in field.flatchoices:
                    labels[f"choice {field.name}={value}"] = label
            for what, label in labels.items():
                with translation.override("en"):
                    english = str(label)
                with translation.override("ar"):
                    arabic = str(label)
                with self.subTest(model=meta.label, label=what):
                    self.assertNotEqual(arabic, english)
                checked += 1
        self.assertGreater(checked, 50)

    def test_unknown_text_falls_back_to_english(self):
        with translation.override("ar"):
            self.assertEqual(translate("A sentence nobody translated"), "A sentence nobody translated")
        with translation.override("en"):
            self.assertEqual(translate("Shop overview"), "Shop overview")

    def test_money_reads_the_same_in_both_languages(self):
        """Django's own Arabic would print 1200,50; the admin must print 1200.50 in both."""
        for lang in ("en", "ar"):
            with translation.override(lang):
                self.assertEqual(formats.number_format(Decimal("1200.50"), decimal_pos=2), "1200.50")


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user("buyer", "buyer@example.com", "pw-not-used-1")
        cls.owner = User.objects.create_superuser("owner", "owner@example.com", "pw-not-used-2")
        cls.product = Product.objects.create(title="Brass clock", title_ar="ساعة نحاسية", price=Decimal("500"), stock=1)
        # A paid order of 1,200.50 EGP, successfully paid.
        cls.paid = Order.objects.create(
            user=cls.customer, status=Order.PAID, total=Decimal("1200.50"),
            full_name="A B", phone="1", address="x", city="c")
        Payment.objects.create(order=cls.paid, status=Payment.SUCCEEDED, amount_cents=120050,
                               paymob_transaction_id="tx-1", succeeded_at=timezone.now())

    def setUp(self):
        self.client.force_login(self.owner)

    def arabic(self):
        self.client.cookies["lang"] = "ar"

    # ---- English stays the default ----
    def test_english_is_the_default(self):
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'dir="ltr"')
        self.assertContains(response, "Shop overview")
        self.assertContains(response, "Orders")
        self.assertNotContains(response, "نظرة عامة")

    # ---- Arabic ----
    def test_home_page_in_arabic_is_right_to_left(self):
        self.arabic()
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, "نظرة عامة على المتجر")
        self.assertContains(response, "الطلبات")
        self.assertContains(response, "المدفوعات")
        self.assertContains(response, "الكتالوج")
        self.assertContains(response, "إدارة")  # Django's own Arabic ("administration") is active too
        self.assertEqual(response["Content-Language"], "ar")

    def test_browser_language_arabic_is_used_when_there_is_no_cookie(self):
        response = self.client.get(reverse("admin:index"), headers={"Accept-Language": "ar-EG,ar;q=0.9"})
        self.assertContains(response, 'dir="rtl"')

    def test_overview_in_arabic_and_money_is_not_flipped(self):
        for lang in ("en", "ar"):
            self.client.cookies["lang"] = lang
            response = self.client.get(reverse("admin_overview"))
            with self.subTest(lang):
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "1,200.50")
                self.assertNotContains(response, "1200,50")
                self.assertNotContains(response, "1.200,50")
        self.assertContains(response, "الإيرادات")
        self.assertContains(response, "بانتظار الدفع")
        self.assertContains(response, "المبيعات (7 أيام)")
        self.assertContains(response, "ج.م")

    def test_order_list_filters_and_actions_in_arabic(self):
        self.arabic()
        response = self.client.get(reverse("admin:order_order_changelist"))
        self.assertContains(response, "رقم التتبع")          # column heading
        self.assertContains(response, "للشحن")               # filter title
        self.assertContains(response, "تحديد الطلبات المدفوعة المختارة كمشحونة")  # action
        self.assertContains(response, "مدفوع")                # status value in the table
        self.assertContains(response, "الطلب %d" % self.paid.pk)  # __str__ of the order

    def test_order_page_help_box_and_labels_in_arabic(self):
        self.arabic()
        response = self.client.get(reverse("admin:order_order_change", args=[self.paid.pk]))
        self.assertContains(response, "شحن الطلب")
        self.assertContains(response, "قائمة الطلبات")
        self.assertContains(response, "الاسم بالكامل")

    def test_product_form_has_clear_english_and_arabic_title_fields(self):
        self.arabic()
        response = self.client.get(reverse("admin:catalog_product_add"))
        self.assertContains(response, "العنوان (بالإنجليزية)")
        self.assertContains(response, "العنوان (بالعربية)")
        self.client.cookies["lang"] = "en"
        response = self.client.get(reverse("admin:catalog_product_add"))
        self.assertContains(response, "Title (English):")
        self.assertContains(response, "Title (Arabic):")

    def test_payments_screens_in_arabic(self):
        self.arabic()
        response = self.client.get(reverse("admin:payments_payment_changelist"))
        self.assertContains(response, "تحتاج إلى مراجعة")
        self.assertContains(response, "ناجحة")
        self.assertContains(response, "طلب استرداد كامل للمدفوعات الناجحة المختارة")

    def test_refused_action_explains_itself_in_arabic(self):
        """Shipping without a tracking number is refused, and the reason is in Arabic."""
        self.arabic()
        response = self.client.post(
            reverse("admin:order_order_changelist"),
            {"action": "mark_shipped", "_selected_action": [self.paid.pk]}, follow=True)
        self.assertContains(response, "أدخل رقم التتبع قبل تحديد الطلب كمشحون.")
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.status, Order.PAID)

    def test_refused_action_in_english(self):
        response = self.client.post(
            reverse("admin:order_order_changelist"),
            {"action": "mark_shipped", "_selected_action": [self.paid.pk]}, follow=True)
        self.assertContains(response, "Enter a tracking number before marking the order shipped.")

    def test_successful_action_message_in_arabic(self):
        self.arabic()
        Order.objects.filter(pk=self.paid.pk).update(tracking_number="TRACK-1")
        response = self.client.post(
            reverse("admin:order_order_changelist"),
            {"action": "mark_shipped", "_selected_action": [self.paid.pk]}, follow=True)
        self.assertContains(response, "الطلب %d: تم الشحن." % self.paid.pk)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.status, Order.SHIPPED)

    # ---- the language button ----
    def test_button_offers_the_other_language(self):
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'name="lang" value="ar"')
        self.arabic()
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'name="lang" value="en"')

    def test_button_switches_language_and_returns_to_the_same_page(self):
        url = reverse("admin_overview") + "?days=30"
        response = self.client.post(reverse("web:preferences"), {"lang": "ar", "next": url})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertEqual(response.cookies["lang"].value, "ar")
        page = self.client.get(url)   # the test client keeps the cookie
        self.assertContains(page, 'dir="rtl"')
        self.assertContains(page, "المبيعات (30 يوماً)")

    def test_button_does_not_redirect_to_other_sites(self):
        response = self.client.post(reverse("web:preferences"), {"lang": "ar", "next": "https://evil.example/"})
        self.assertNotIn("evil.example", response["Location"])

    def test_login_page_has_the_button_and_follows_the_language(self):
        self.client.logout()
        self.arabic()
        response = self.client.get(reverse("admin:login"))
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'name="lang" value="en"')
        self.client.cookies["lang"] = "en"
        response = self.client.get(reverse("admin:login"))
        self.assertContains(response, 'name="lang" value="ar"')

    # ---- nothing else changed ----
    def test_json_api_stays_english(self):
        self.client.logout()
        self.arabic()
        response = self.client.get("/api/order/", headers={"Accept-Language": "ar"})
        self.assertEqual(response.status_code, 401)
        self.assertContains(response, "Authentication credentials were not provided.", status_code=401)

    def test_arabic_in_the_admin_does_not_leak_into_the_next_request(self):
        self.arabic()
        self.client.get(reverse("admin:index"))
        self.client.cookies["lang"] = "en"
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'dir="ltr"')
