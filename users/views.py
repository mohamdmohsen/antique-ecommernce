from rest_framework import  status
from rest_framework.response import Response
from rest_framework.decorators import api_view ,permission_classes
from rest_framework.permissions import AllowAny,IsAuthenticated

from .serializers import RegisterSerializer ,UserSerializers
# Create your views here.

@api_view(["POST"])
def register(request):
    serializer =RegisterSerializer(data = request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)    
    return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    serializer = UserSerializers(request.user)
    return Response(serializer.data)

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_me(request):
    serilaizers = UserSerializers(request.user,data = request.data ,partial =True)
    if serilaizers.is_valid():
        serilaizers.save()
        return Response(serilaizers.data,status=status.HTTP_200_OK)
    return Response(serilaizers.errors,status=status.HTTP_400_BAD_REQUEST)