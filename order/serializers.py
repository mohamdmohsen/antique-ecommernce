from .models import Order,OrderItem
from rest_framework import serializers
from users.policies import require_confirmation



class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ("product", "title", "price", "quantity")


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id", "status", "total", "full_name", "phone",
            "address", "city", "tracking_number", "created_at", "items",
        )

class CheckoutSerializer(serializers.ModelSerializer):
    terms_accepted = serializers.BooleanField(write_only=True, validators=[require_confirmation])
    buyer_confirmed = serializers.BooleanField(write_only=True, validators=[require_confirmation])
    class Meta:
        model = Order
        fields = ("full_name", "phone", "address", "city", "terms_accepted", "buyer_confirmed")
