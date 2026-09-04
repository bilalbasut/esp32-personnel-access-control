import time
from rest_framework import serializers
from devices.models import Device

VALID_COMMANDS = {"open", "sync", "reboot", "settime"}


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        # "__all__" değil: client PATCH ile deleted_at'i elle set edip delete()'i (ve audit'i) atlayabilirdi.
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