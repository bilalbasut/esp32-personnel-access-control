import time
from rest_framework import serializers
from devices.models import Device

VALID_COMMANDS = {"open", "sync", "reboot", "settime"}


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = "__all__"


class DeviceCommandSerializer(serializers.Serializer):
    cmd = serializers.ChoiceField(choices=list(VALID_COMMANDS))
    payload = serializers.DictField(required=False, default=dict)


class DeviceOTASerializer(serializers.Serializer):
    version = serializers.CharField(max_length=50)