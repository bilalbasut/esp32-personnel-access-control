import json
import os
import time

from django.conf import settings
from django.db import connection
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.audit import log_action
from core import mqtt_utils
from core.models import Firmware
from devices.models import Device
from devices.serializers import DeviceCommandSerializer, DeviceOTASerializer, DeviceSerializer


def _next_cmd_seq():
    """Modül seviyesinde bir itertools.count() yerine core'un migration'larında
    oluşturulmuş 'cmd_sequence' Postgres sequence'inden çekiyor. Process-içi
    sayaç sadece TEK worker process'te doğru çalışır - README'nin önerdiği
    `gunicorn --workers N` altında her worker kendi import anından başlayan
    kendi sayacına sahip olur, yani farklı worker'ların işlediği istekler
    çakışan/tekrar eden seq numaraları dağıtır. Asıl çözüm bir DB sequence -
    core/acl.py'nin ACL versiyonlarını zaten aynı şekilde kaynaklamasıyla aynı mantık."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('cmd_sequence')")
        return cursor.fetchone()[0]


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all().order_by("id")
    serializer_class = DeviceSerializer
    lookup_field = "id"

    def perform_create(self, serializer):
        device = serializer.save()
        log_action(self.request, "device.create", f"Device {device.id} ({device.name})")

    def perform_update(self, serializer):
        device = serializer.save()
        log_action(self.request, "device.update", f"Device {device.id} ({device.name})")

    def perform_destroy(self, instance):
        log_action(self.request, "device.delete", f"Device {instance.id} ({instance.name})")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="command")
    def send_command(self, request, *args, **kwargs):
        """Operasyonel donanım komutlarını (open, sync, reboot) ESP32'ye gönderir."""
        serializer = DeviceCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cmd = serializer.validated_data["cmd"]
        extra = serializer.validated_data.get("payload", {})

        device = self.get_object()
        seq = _next_cmd_seq()
        topic = f"pdks/merkez/dev/{device.id}/cmd"

        payload = {
            "cmd": cmd,
            "seq": seq,
            "ts": int(time.time()),
            **extra
        }

        try:
            mqtt_utils.publish(topic, json.dumps(payload))
            log_action(
                request, "device.command", f"Device {device.id}",
                details={"cmd": cmd, "seq": seq}
            )
            return Response({"status": "queued", "topic": topic, "seq": seq})
        except Exception as e:
            return Response(
                {"error": f"MQTT publish failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["post"], url_path="ota")
    def ota(self, request, *args, **kwargs):
        """Checksum ve binary URL ile bir OTA firmware güncelleme komutu gönderir."""
        device = self.get_object()
        serializer = DeviceOTASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_version = serializer.validated_data["version"].strip()

        if not raw_version:
            return Response(
                {"error": "Firmware version parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Başındaki 'v' harfini tolere etmek için versiyon string'ini normalize et
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

        server_ip = getattr(settings, "PANEL_BASE_URL", os.environ.get("PANEL_BASE_URL"))
        if not server_ip:
            return Response(
                {"error": "PANEL_BASE_URL is not configured in settings or environment."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        ota_url = f"{server_ip}/api/firmware/{fw.version}/download"
        topic = f"pdks/merkez/dev/{device.id}/cmd"
        seq = _next_cmd_seq()

        payload = {
            "cmd": "ota",
            "seq": seq,
            "url": ota_url,
            "version": str(fw.version),
            "md5": md5_hash,
            "size": int(getattr(fw, "size", 0) or 0)
        }

        try:
            mqtt_utils.publish(topic, json.dumps(payload))
            log_action(
                request, "device.ota", f"Device {device.id}",
                details={"seq": seq, "version": str(fw.version)}
            )
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