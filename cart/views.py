from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Product
from .models import CartItem
from .serializers import CartItemSerializer, AddToCartSerializer
# Create your views here.



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def cart_details(request):
    items = CartItem.objects.filter(user=request.user).select_related("product")
    total = sum(item.product.price * item.quantity for item in items)
    return Response({
        "items": CartItemSerializer(items,many =True).data,
        "total":total,
    })



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_to_cart(request, pk):
    # the product id comes from the URL (cart/add/<pk>/), the quantity from the body
    serializer = AddToCartSerializer(
        data={"product": pk, "quantity": request.data.get("quantity", 1)}
    )
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    product = get_object_or_404(Product, pk=pk)

    item = CartItem.objects.filter(user=request.user, product=product).first()
    current = item.quantity if item else 0
    new_quantity = current + serializer.validated_data["quantity"]

    if new_quantity > product.stock:
        return Response({"error": "Not enough stock"}, status=status.HTTP_400_BAD_REQUEST)

    if item:
        item.quantity = new_quantity
        item.save()
    else:
        CartItem.objects.create(user=request.user, product=product, quantity=new_quantity)

    return Response({"message": "Added to cart"}, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def remove_from_cart(request, pk):
    item = get_object_or_404(CartItem, pk=pk, user=request.user)
    item.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

