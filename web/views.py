from functools import wraps
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from cart.models import CartItem
from cart.services import CartError, add_item, remove_item
from catalog.models import Product
from order.models import Order
from order.services import CheckoutError, create_order_from_cart
from payments.models import Payment
from payments.services import PaymentStartError, start_payment_for_order
from users.accounts import send_password_reset, send_verification
from users.throttles import EmailThrottle, LoginThrottle
from users.views import deliver
from .forms import DeliveryForm, EmailForm, QuantityForm, RegisterForm, SignInForm, localize
from .i18n import LANGUAGES
from .middleware import COOKIE_MAX_AGE


def safe_next(request):
    value = request.POST.get('next') or request.GET.get('next') or reverse('web:shop')
    if not url_has_allowed_host_and_scheme(value, {request.get_host()}, require_https=request.is_secure()):
        return reverse('web:shop')
    return value


def verified_customer(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(reverse('web:login') + '?' + urlencode({'next': request.get_full_path()}))
        if not request.user.email_verified:
            logout(request)
            messages.error(request, request.t['err_unverified'])
            return redirect('web:login')
        return view(request, *args, **kwargs)
    return wrapped


def limited(request, throttle_class):
    throttle = throttle_class()
    allowed = throttle.allow_request(SimpleNamespace(data=request.POST, META=request.META), None)
    return None if allowed else max(1, int(throttle.wait()))


def form_page(request, form, title, button, *, done=False, status=200):
    return render(request, 'web/form.html', {'form': localize(form, request.t), 'title': title,
        'button': button, 'done': done, 'throttled': status == 429, 'next': safe_next(request)}, status=status)


@require_http_methods(['GET'])
def shop(request):
    products = Product.objects.all()
    search = request.GET.get('search', '').strip()[:200]
    if search:
        products = products.filter(Q(title__icontains=search) | Q(title_ar__icontains=search) |
                                   Q(description__icontains=search) | Q(description_ar__icontains=search))
    ordering = request.GET.get('ordering', '-id')
    if ordering not in {'-id', 'price', '-price'}:
        ordering = '-id'
    page = Paginator(products.order_by(ordering, 'pk'), 24).get_page(request.GET.get('page'))
    return render(request, 'web/shop.html', {'page': page, 'search': search, 'ordering': ordering,
        'page_query': urlencode({'search': search, 'ordering': ordering})})


@require_http_methods(['GET'])
def product(request, pk):
    return render(request, 'web/product.html', {'product': get_object_or_404(Product, pk=pk),
        'form': localize(QuantityForm(), request.t)})


@require_POST
@verified_customer
def add(request, pk):
    form = QuantityForm(request.POST)
    if form.is_valid():
        try:
            add_item(request.user, pk, form.cleaned_data['quantity'])
            messages.success(request, request.t['msg_added'])
            return redirect('web:cart')
        except CartError:
            messages.error(request, request.t['err_stock'])
    else:
        messages.error(request, request.t['err_quantity'])
    return redirect('web:product', pk=pk)


def cart_rows(user):
    items = list(CartItem.objects.filter(user=user).select_related('product').order_by('pk'))
    return items, sum(item.product.price * item.quantity for item in items)


@require_http_methods(['GET'])
@verified_customer
def cart(request):
    items, total = cart_rows(request.user)
    return render(request, 'web/cart.html', {'items': items, 'total': total})


@require_POST
@verified_customer
def remove(request, pk):
    remove_item(request.user, pk)
    return redirect('web:cart')


@require_http_methods(['GET', 'POST'])
@verified_customer
def checkout(request):
    form = DeliveryForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            order = create_order_from_cart(request.user, form.cleaned_data)
            messages.success(request, request.t['msg_order_placed'])
            return redirect('web:order', pk=order.pk)
        except CheckoutError as exc:
            form.add_error(None, request.t['err_empty_cart' if exc.code == 'empty' else 'err_stock_order'])
    items, total = cart_rows(request.user)
    return render(request, 'web/checkout.html', {'form': localize(form, request.t), 'items': items, 'total': total})


@require_http_methods(['GET'])
@verified_customer
def orders(request):
    page = Paginator(Order.objects.filter(user=request.user).order_by('-created_at', '-pk'), 20).get_page(request.GET.get('page'))
    return render(request, 'web/orders.html', {'page': page})


@require_http_methods(['GET'])
@verified_customer
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)
    return render(request, 'web/order.html', {'order': order,
        'payment': order.payments.order_by('-pk').first()})


@require_POST
@verified_customer
def pay(request, pk):
    try:
        target = start_payment_for_order(pk, request.user)
    except PaymentStartError as exc:
        messages.error(request, request.t['pay_err_' + exc.code])
        return redirect('web:order', pk=pk)
    # The service constructs this URL from server settings, never request input.
    request.session['payment_order'] = pk
    return HttpResponseRedirect(target)


@require_http_methods(['GET'])
@verified_customer
def payment_result(request):
    pk = request.session.get('payment_order')
    if pk and Order.objects.filter(pk=pk, user=request.user).exists():
        # Provider query-string status is deliberately ignored; DB/webhook wins.
        return redirect('web:order', pk=pk)
    return redirect('web:orders')


@require_http_methods(['GET', 'POST'])
def sign_in(request):
    form = SignInForm(request, data=request.POST if request.method == 'POST' else None)
    retry = limited(request, LoginThrottle) if request.method == 'POST' else None
    if retry:
        response = form_page(request, form, request.t['login_title'], request.t['login_button'], status=429)
        response['Retry-After'] = str(retry)
        return response
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect(safe_next(request))
    return form_page(request, form, request.t['login_title'], request.t['login_button'])


@require_POST
def sign_out(request):
    logout(request)
    return redirect('web:shop')


@require_http_methods(['GET', 'POST'])
def register(request):
    form = RegisterForm(request.POST if request.method == 'POST' else None)
    retry = limited(request, EmailThrottle) if request.method == 'POST' else None
    if retry:
        response = form_page(request, form, request.t['register_title'], request.t['register_button'], status=429)
        response['Retry-After'] = str(retry)
        return response
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        deliver(send_verification, user)
        return form_page(request, form, request.t['register_done_title'], request.t['register_button'], done=request.t['register_done_text_b'])
    return form_page(request, form, request.t['register_title'], request.t['register_button'])


@require_http_methods(['GET', 'POST'])
def email_help(request, resend=False):
    form = EmailForm(request.POST if request.method == 'POST' else None)
    title = request.t['resend_title' if resend else 'forgot_title']
    retry = limited(request, EmailThrottle) if request.method == 'POST' else None
    if retry:
        response = form_page(request, form, title, request.t['send_link'], status=429)
        response['Retry-After'] = str(retry)
        return response
    if request.method == 'POST' and form.is_valid():
        email = form.cleaned_data['email']
        if resend:
            user = get_user_model().objects.filter(email__iexact=email, email_verified=False).first()
            if user:
                deliver(send_verification, user)
        else:
            deliver(send_password_reset, email)
        return form_page(request, form, title, request.t['send_link'], done=request.t['resend_done' if resend else 'forgot_done'])
    return form_page(request, form, title, request.t['send_link'])


@require_POST
def preferences(request):
    response = redirect(safe_next(request))
    for name, allowed in [('lang', LANGUAGES), ('theme', ('light', 'dark'))]:
        value = request.POST.get(name)
        if value in allowed:
            response.set_cookie(name, value, max_age=COOKIE_MAX_AGE, samesite='Lax',
                                httponly=True, secure=request.is_secure())
    return response
