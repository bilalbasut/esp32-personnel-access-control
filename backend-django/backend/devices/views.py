import itertools
import json
import os
import time

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core import mqtt_utils
from core.models import Firmware
from devices.models import Device
from devices.serializers import DeviceCommandSerializer, DeviceSerializer

_cmd_seq_counter = itertools.count(int(time.time()) + 1)


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all().order_by("id")
    serializer_class = DeviceSerializer
    lookup_field = "id"

    @action(detail=True, methods=["post"], url_path="command")
    def send_command(self, request, *args, **kwargs):
        """Dispatches operational hardware commands (open, sync, reboot) to the ESP32."""
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
            return Response(
                {"error": f"MQTT publish failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["post"], url_path="ota")
    def ota(self, request, *args, **kwargs):
        """Dispatches an OTA firmware update command with checksum and binary URL."""
        device = self.get_object()
        raw_version = str(request.data.get("version", "")).strip()

        if not raw_version:
            return Response(
                {"error": "Firmware version parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Normalize version string to tolerate leading 'v'
        clean_version = raw_version.lstrip("v")
        fw = (
            Firmware.objects.filter(version=raw_version).first()
            or Firmware.objects.filter(version=clean_version).first()
            or Firmware.objects.filter(version=f"v{clean_version}").first()
        )

        if not fw:
            return Response(
                {"error": f"Firmware version '{raw_version}' not found in registry."},
                status=status.HTTP_404_NOT_FOUND
            )

        md5_hash = str(getattr(fw, "md5", "") or "").strip().lower()
        if len(md5_hash) != 32:
            return Response(
                {"error": f"Firmware v{fw.version} has an invalid MD5 hash in the database."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        server_ip = getattr(settings, "HOST_LAN_IP", os.environ.get("HOST_LAN_IP", "192.168.1.50"))
        ota_url = f"http://{server_ip}:3000/api/firmware/{fw.version}/download"
        topic = f"pdks/merkez/dev/{device.id}/cmd"
        seq = next(_cmd_seq_counter)

        payload = {
            "cmd": "ota",
            "seq": seq,
            "url": ota_url,
            "version": str(fw.version),
            "md5": md5_hash,
            "size": int(getattr(fw, "file_size", 0) or 0)
        }

        try:
            mqtt_utils.publish(topic, json.dumps(payload))
            return Response({
                "status": "queued",
                "seq": seq,
                "ota_url": ota_url,
                "md5": md5_hash
            })
        except Exception as e:
            return Response(
                {"error": f"MQTT publish failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )