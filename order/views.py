from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .serializers import CheckoutSerializer, OrderSerializer

from cart.models import CartItem
from catalog.models import Product
from .models import Order, OrderItem
from .serializers import CheckoutSerializer
# Create your views here.


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def checkout(request):
    serializer = CheckoutSerializer(data =request.data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        cart_items = list(
            CartItem.objects.filter(user=request.user).order_by("product_id")
        )

        if not cart_items:
            raise ValidationError({"error": "Cart is empty"})

        order = Order.objects.create(
            user=request.user, total=0, **serializer.validated_data
        )

        total = 0
        for item in cart_items:
            product = Product.objects.select_for_update().get(pk=item.product_id)

        if item.quantity > product.stock:
                raise ValidationError(
                    {"error": f"Not enough stock for {product.title}"}
                )

        product.stock -= item.quantity
        product.save(update_fields=["stock"])

        OrderItem.objects.create(
                order=order,
                product=product,
                title=product.title,
                price=product.price,
                quantity=item.quantity,
            )
        total += product.price * item.quantity

        order.total = total
        order.save(update_fields=["total"])

        CartItem.objects.filter(user=request.user).delete()

    return Response({"id": order.id, "total": total}, status=status.HTTP_201_CREATED)




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def order_list(request):
    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related("items")
        .order_by("-created_at")
    )
    return Response(OrderSerializer(orders, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk, user=request.user)
    return Response(OrderSerializer(order).data)