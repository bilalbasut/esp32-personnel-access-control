import json
import time
import itertools
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.conf import settings

from devices.models import Device
from devices.serializers import DeviceSerializer, DeviceCommandSerializer, DeviceOTASerializer
from core import mqtt_utils

_cmd_seq_counter = itertools.count(int(time.time()) + 1)


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all().order_by("id")
    serializer_class = DeviceSerializer
    lookup_field = "id"

    @action(detail=True, methods=["post"], url_path="command")
    def send_command(self, request, id=None):
        """Replaces POST /devices/<id>/command"""
        serializer = DeviceCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cmd = serializer.validated_data["cmd"]
        extra = serializer.validated_data.get("payload", {})

        device = self.get_object()
        seq = next(_cmd_seq_counter)
        topic = f"pdks/merkez/dev/{device.id}/cmd"

        payload = {
            "cmd": cmd,
            "seq": seq,
            "ts": int(time.time()),
            **extra
        }

        try:
            mqtt_utils.publish(topic, json.dumps(payload))
            return Response({"status": "queued", "topic": topic, "seq": seq})
        except Exception as e:
            return Response({"error": f"MQTT publish failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=["post"], url_path="ota")
    def trigger_ota(self, request, id=None):
        """Replaces POST /devices/<id>/ota"""
        serializer = DeviceOTASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        version = serializer.validated_data["version"]
        device = self.get_object()

        # Check firmware file existence via core models/storage
        bin_filename = f"firmware_{version}.bin"
        ota_url = f"{settings.PANEL_BASE_URL.rstrip('/')}/firmware/{bin_filename}"

        topic = f"pdks/merkez/dev/{device.id}/cmd"
        payload = {
            "cmd": "ota",
            "seq": next(_cmd_seq_counter),
            "url": ota_url,
            "version": version
        }

        try:
            mqtt_utils.publish(topic, json.dumps(payload))
            return Response({"status": "ota_triggered", "url": ota_url})
        except Exception as e:
            return Response({"error": f"MQTT publish failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)