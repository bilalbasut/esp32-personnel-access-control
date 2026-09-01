import re
from rest_framework import serializers
from core.models import AccessEvent, Firmware

VERSION_RE = re.compile(r"^[a-zA-Z0-9._-]{1,50}$")


class AccessEventSerializer(serializers.ModelSerializer):
    ad_soyad = serializers.CharField(read_only=True)
    departman = serializers.CharField(read_only=True)

    class Meta:
        model = AccessEvent
        fields = "__all__"


class FirmwareSerializer(serializers.ModelSerializer):
    class Meta:
        model = Firmware
        fields = ["version", "filename", "md5", "size", "uploaded_at"]


class FirmwareUploadSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=50)
    file = serializers.FileField()

    def validate_version(self, value):
        if not VERSION_RE.match(value):
            raise serializers.ValidationError(
                "Version format invalid. Must match ^[a-zA-Z0-9._-]{1,50}$"
            )
        return value