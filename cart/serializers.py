from rest_framework import serializers
from .models import CartItem


class CartItemSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source = "product.title",read_only = True)
    class Meta:
        model = CartItem
        fields = ("id", "product", "title", "price", "quantity")



class AddToCartSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)