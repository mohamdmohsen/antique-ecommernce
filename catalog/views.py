from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Product
from .serializers import ProductSerializer
# Create your views here.


class ProductPagination(PageNumberPagination):
    page_size = 24
    page_size_query_param = "page_size"
    max_page_size = 100


@api_view(["GET"])
def product_list(request):
    products = Product.objects.all()
    search = request.query_params.get("search", "").strip()[:200]
    if search:
        products = products.filter(Q(title__icontains=search) | Q(description__icontains=search))
    ordering = request.query_params.get("ordering", "id")
    if ordering not in {"id", "-id", "title", "-title", "price", "-price"}:
        raise ValidationError({"ordering": "Choose id, title or price, optionally prefixed with -."})
    products = products.order_by(ordering, "pk")
    paginator = ProductPagination()
    page = paginator.paginate_queryset(products, request)
    return paginator.get_paginated_response(ProductSerializer(page, many=True).data)


@api_view(["GET"])
def product_details(request,pk):
   product = get_object_or_404(Product,pk =pk)    
   serializer = ProductSerializer(product ,many =False)
   return Response(serializer.data,status=status.HTTP_200_OK)


