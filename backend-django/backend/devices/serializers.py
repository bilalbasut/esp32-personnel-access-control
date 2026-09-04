import time
from rest_framework import serializers
from devices.models import Device

VALID_COMMANDS = {"open", "sync", "reboot", "settime"}


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        # BİLEREK "__all__" DEĞİL: Device artık BaseModel'den created_by/
        # updated_by/deleted_by/deleted_at gibi bookkeeping alanları
        # taşıyor - "__all__" bunları DA client'ın PATCH/POST body'sinden
        # doğrudan yazabileceği alanlar yapardı (örn. bir istemci deleted_at'i
        # elle set edip delete()'i, dolayısıyla audit log'u ve is_active
        # senkronunu hiç tetiklemeden bir satırı "silinmiş" gösterebilirdi).
        # created_at/updated_at/created_by/updated_by görüntülemek için
        # read-only olarak dahil edildi (bkz. read_only_fields);
        # deleted_at/deleted_by hiç dahil edilmedi - onlar sadece delete()
        # üzerinden değişmeli (core/audit_viewset.py AuditedModelViewSet).
        fields = [
            "id", "name", "floor", "location", "ip_address", "mac_address",
            "last_seen_at", "status", "fw", "queue_depth", "heap_free",
            "queue_overflow", "uptime_s", "ota_status", "ota_updated_at",
            "is_active", "created_at", "updated_at", "created_by", "updated_by",
        ]
        read_only_fields = ["created_at", "updated_at", "created_by", "updated_by"]


class DeviceCommandSerializer(serializers.Serializer):
    cmd = serializers.ChoiceField(choices=list(VALID_COMMANDS))
    payload = serializers.DictField(required=False, default=dict)


class DeviceOTASerializer(serializers.Serializer):
    version = serializers.CharField(max_length=50)