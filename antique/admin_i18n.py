"""Arabic text for the admin dashboard.

Same idea as web/i18n.py (the website's sentences): no extra tools to install and
nothing to compile. The key is the English text, the value is the Arabic.

How to translate something new:
  * in Python:    t("English text")            (a lazy string, safe in models/admin)
  * in a template: {% load admin_i18n %} {% tr "English text" %}
  * then add  "English text": "النص العربي",  to AR below.

Django's own admin screens (Save, Delete, Search, Log in ...) are already translated
by Django itself; only the shop's own words live here. A test (antique/test_admin_i18n.py)
fails if a t("...") or {% tr "..." %} in the code has no Arabic entry below, so a
missing translation cannot slip through.
"""
from django.utils import translation
from django.utils.functional import lazy

AR = {
    # ---- sections on the admin home page (one per app) ----
    "Catalog": "الكتالوج",
    "Order": "الطلبات",
    "Payments": "المدفوعات",
    "Users": "المستخدمون",

    # ---- model names (singular / plural) ----
    "product": "منتج",
    "products": "المنتجات",
    "order": "طلب",
    "orders": "الطلبات",
    "order item": "عنصر طلب",
    "order items": "عناصر الطلبات",
    "order status event": "حدث في حالة الطلب",
    "order status events": "أحداث حالة الطلبات",
    "payment": "دفعة",
    "payments": "المدفوعات",
    "refund": "استرداد",
    "refunds": "المستردات",
    "webhook event": "إشعار دفع (Webhook)",
    "webhook events": "إشعارات الدفع (Webhook)",
    "policy acceptance": "موافقة على السياسات",
    "policy acceptances": "الموافقات على السياسات",

    # ---- field names ----
    "title (English)": "العنوان (بالإنجليزية)",
    "title (Arabic)": "العنوان (بالعربية)",
    "description (English)": "الوصف (بالإنجليزية)",
    "description (Arabic)": "الوصف (بالعربية)",
    "price": "السعر",
    "image": "الصورة",
    "stock": "المخزون",
    "user": "مستخدم",
    "status": "الحالة",
    "total": "الإجمالي",
    "full name": "الاسم بالكامل",
    "phone": "رقم الهاتف",
    "address": "العنوان",
    "city": "المدينة",
    "tracking number": "رقم التتبع",
    "created at": "تاريخ الإنشاء",
    "updated at": "تاريخ التحديث",
    "succeeded at": "تاريخ نجاح الدفع",
    "title": "العنوان",
    "quantity": "الكمية",
    "actor": "المنفِّذ",
    "previous status": "الحالة السابقة",
    "intention state": "حالة صفحة الدفع",
    "amount cents": "المبلغ (بالقروش)",
    "currency": "العملة",
    "client secret": "المفتاح السري للعميل",
    "paymob order id": "رقم الطلب في Paymob",
    "paymob transaction id": "رقم المعاملة في Paymob",
    "needs attention": "تحتاج إلى مراجعة",
    "note": "ملاحظة",
    "transaction id": "رقم المعاملة",
    "payload": "البيانات المستلمة",
    "hmac valid": "التوقيع صحيح (HMAC)",
    "requested by": "طُلب بواسطة",
    "provider id": "معرّف مزوّد الدفع",
    "purpose": "الغرض",
    "policy version": "إصدار السياسات",
    "age confirmed": "تأكيد السن",
    "buyer capacity confirmed": "تأكيد أهلية الشراء",

    # ---- statuses and other choices ----
    "Pending": "قيد الانتظار",
    "Paid": "مدفوع",
    "Shipped": "تم الشحن",
    "Delivered": "تم التسليم",
    "Cancelled": "ملغي",
    "Succeeded": "ناجحة",
    "Failed": "فاشلة",
    "Refunded": "مستردة",
    "Not started": "لم تبدأ",
    "Creating checkout": "جارٍ إنشاء صفحة الدفع",
    "Checkout identified": "تم تحديد صفحة الدفع",
    "Needs reconciliation": "تحتاج إلى مطابقة",
    "Registration": "التسجيل",
    "Checkout": "إتمام الشراء",

    # ---- order / payment list screens ----
    "To ship": "للشحن",
    "Paid orders without refunds": "طلبات مدفوعة بدون استرداد",
    "Mark selected paid orders shipped": "تحديد الطلبات المدفوعة المختارة كمشحونة",
    "Mark selected shipped orders delivered": "تحديد الطلبات المشحونة المختارة كمسلَّمة",
    "Request full refund for selected successful payments": "طلب استرداد كامل للمدفوعات الناجحة المختارة",
    "Order %(id)s: %(status)s.": "الطلب %(id)s: %(status)s.",
    "Payment %(id)s: refund %(status)s.": "الدفعة %(id)s: الاسترداد %(status)s.",
    "Order %(id)s - %(user)s": "الطلب %(id)s - %(user)s",
    "Payment %(id)s for order %(order)s (%(status)s)": "الدفعة %(id)s للطلب %(order)s (%(status)s)",
    "Refund %(id)s for payment %(payment)s (%(status)s)": "الاسترداد %(id)s للدفعة %(payment)s (%(status)s)",

    # ---- errors the owner can see when an action is refused ----
    "You do not have permission to change fulfillment status.": "ليس لديك صلاحية تغيير حالة تنفيذ الطلب.",
    "Only paid → shipped → delivered transitions are allowed.": "المسموح فقط: مدفوع ← مشحون ← مسلَّم.",
    "The order needs a confirmed, unrefunded payment before fulfillment.": "يحتاج الطلب إلى دفعة مؤكدة وغير مستردة قبل تنفيذه.",
    "Resolve the refund before fulfilling this order.": "عالج عملية الاسترداد قبل تنفيذ هذا الطلب.",
    "Enter a tracking number before marking the order shipped.": "أدخل رقم التتبع قبل تحديد الطلب كمشحون.",
    "You do not have permission to issue refunds.": "ليس لديك صلاحية إصدار عمليات الاسترداد.",
    "Configure the Paymob refund API key before requesting a refund.": "اضبط مفتاح واجهة الاسترداد في Paymob قبل طلب الاسترداد.",
    "Only a successful payment with a provider transaction ID can be refunded.": "يمكن استرداد الدفعات الناجحة التي لها رقم معاملة لدى مزوّد الدفع فقط.",

    # ---- admin home page link ----
    "Shop overview": "نظرة عامة على المتجر",
    "revenue, orders to ship, payments needing attention": "الإيرادات، والطلبات المطلوب شحنها، والمدفوعات التي تحتاج إلى مراجعة",

    # ---- shop overview page ----
    "Revenue": "الإيرادات",
    "EGP": "ج.م",
    "EGP, paid orders, after refunds": "بالجنيه المصري، للطلبات المدفوعة، بعد خصم المستردات",
    "Paid orders": "الطلبات المدفوعة",
    "Awaiting payment": "بانتظار الدفع",
    "paid, not shipped yet": "مدفوعة ولم تُشحن بعد",
    "Payments needing attention": "مدفوعات تحتاج إلى مراجعة",
    "check these first": "ابدأ بهذه",
    "Customers": "العملاء",
    "Products": "المنتجات",
    "sold out": "نفدت",
    "Sales": "المبيعات",
    "7 days": "7 أيام",
    "30 days": "30 يوماً",
    "Total for this period:": "إجمالي هذه الفترة:",
    "Older successful payments with no known confirmation date are included in lifetime revenue but excluded from this chart. Count:":
        "الدفعات الناجحة القديمة التي لا يُعرف تاريخ تأكيدها محسوبة ضمن إجمالي الإيرادات منذ البداية لكنها مستبعدة من هذا الرسم. العدد:",
    "Day by day": "يوماً بيوم",
    "Date": "التاريخ",
    "Sales (EGP)": "المبيعات (ج.م)",
    "No sales in this period.": "لا توجد مبيعات في هذه الفترة.",

    # ---- "Shipping an order" help box on the order page ----
    "Shipping an order": "شحن الطلب",
    "Status changes follow paid → shipped → delivered. Pending orders are awaiting confirmed payment and cannot be shipped.":
        "تتغير الحالة بالترتيب: مدفوع ← مشحون ← مسلَّم. الطلبات قيد الانتظار تنتظر تأكيد الدفع ولا يمكن شحنها.",
    "Wait for the payment confirmation to mark the order paid. Orders with a refund cannot be fulfilled.":
        "انتظر تأكيد الدفع ليتحول الطلب إلى «مدفوع». لا يمكن تنفيذ الطلبات التي فيها استرداد.",
    "Enter the tracking number below and save the order.": "أدخل رقم التتبع في الأسفل ثم احفظ الطلب.",
    "Return to the": "ارجع إلى",
    "orders list": "قائمة الطلبات",
    ", select the order, choose": "، حدّد الطلب، ثم اختر",
    "in Actions, and click Go.": "من قائمة الإجراءات، ثم اضغط «اذهب».",
    "After delivery, select": "بعد التسليم، اختر",
    "from the same list.": "من القائمة نفسها.",
}


def translate(text):
    """English text -> text in the language the admin page is using right now."""
    if (translation.get_language() or "").startswith("ar"):
        return AR.get(text, text)
    return text


# Lazy, so a label written once in a model or admin class is translated each time
# it is shown (not once when the server starts).
t = lazy(translate, str)
