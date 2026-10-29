from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth import get_user_model
from order.models import Order


class SignInForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.email_verified:
            raise forms.ValidationError('Verify your email before signing in.', code='unverified')


class RegisterForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'email')


class EmailForm(forms.Form):
    email = forms.EmailField()


class QuantityForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=99, initial=1)


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ('full_name', 'phone', 'address', 'city')


def localize(form, strings):
    for name, field in form.fields.items():
        key = {'password1': 'password', 'password2': 'confirm_password'}.get(name, name)
        if key in strings:
            field.label = strings[key]
    return form
