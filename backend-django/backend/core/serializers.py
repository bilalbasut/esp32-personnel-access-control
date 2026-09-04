import re
from rest_framework import serializers
from core.models import AccessEvent, Firmware

VERSION_RE = re.compile(r"^[a-zA-Z0-9._-]{1,50}$")


class AccessEventSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    department = serializers.CharField(read_only=True)

    class Meta:
        model = AccessEvent
        # "__all__" burada fiilen zararsız (EventViewSet sadece ListModelMixin,
        # hiçbir create/update/destroy endpoint'i bu serializer'ı yazma
        # amaçlı kullanmıyor) ama yine de BaseModel'in bookkeeping alanlarını
        # (created_by/updated_by/deleted_by) read-only işaretlemek, DeviceSerializer'daki
        # aynı disiplinle tutarlı kalmak ve ileride bu serializer'a bir yazma
        # yolu eklenirse sürpriz yaşanmamasını garanti etmek için.
        fields = "__all__"
        read_only_fields = ["created_at", "updated_at", "created_by", "updated_by", "deleted_at", "deleted_by"]


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