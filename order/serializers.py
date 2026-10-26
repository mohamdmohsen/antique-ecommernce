from .models import Order,OrderItem
from rest_framework import serializers



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
    class Meta:
        model = Order
        fields = ("full_name", "phone", "address", "city")
