from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .serializers import CheckoutSerializer, OrderSerializer

from .models import Order
from .services import CheckoutError, create_order_from_cart
# Create your views here.


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def checkout(request):
    serializer = CheckoutSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        order = create_order_from_cart(request.user, serializer.validated_data)
    except CheckoutError as error:
        raise ValidationError({"error": error.message})

    return Response({"id": order.id, "total": order.total}, status=status.HTTP_201_CREATED)


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
