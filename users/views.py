from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .serializers import RegisterSerializer, UserSerializers
from .throttles import EmailThrottle


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailThrottle])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(UserSerializers(request.user).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_me(request):
    serializer = UserSerializers(request.user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)
