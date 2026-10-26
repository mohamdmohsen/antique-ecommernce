from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Product
from .serializers import ProductSerializer
# Create your views here.


@api_view(['GET'])
def product_list(request):
    product = Product.objects.filter()
    serializer = ProductSerializer(product,many = True)
    return Response(serializer.data,status=status.HTTP_200_OK)


@api_view(["GET"])
def product_details(request,pk):
   product = get_object_or_404(Product,pk =pk)    
   serializer = ProductSerializer(product ,many =False)
   return Response(serializer.data,status=status.HTTP_200_OK)


