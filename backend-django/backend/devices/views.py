from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Device
from .serializers import DeviceSerializer
# from core.mqtt_utils import mqtt_client  # Import core utils here when needed

class DeviceViewSet(viewsets.ModelViewSet):
    """
    Standard CRUD is automatically handled by ModelViewSet.
    Custom FBVs are refactored into the @action methods below.
    """
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer

    # Replaces a raw FBV like `def ping_device(request, pk):`
    @action(detail=True, methods=['post'])
    def ping(self, request, pk=None):
        device = self.get_object()
        # Execute MQTT ping or core logic here
        return Response({'status': 'Ping command sent', 'device': device.mac_address})

    # Replaces a raw FBV like `def get_active_devices(request):`
    @action(detail=False, methods=['get'])
    def active(self, request):
        active_devices = self.queryset.filter(is_active=True)
        serializer = self.get_serializer(active_devices, many=True)
        return Response(serializer.data)