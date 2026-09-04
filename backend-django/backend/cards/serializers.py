from rest_framework import serializers
from cards.models import Card, Employee
from core.acl import parse_floors


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "full_name", "department", "employee_no", "email", "phone", "is_active"]


class CardSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), source="employee", write_only=True, required=False, allow_null=True
    )

    class Meta:
        model = Card
        fields = [
            "uid", "employee", "employee_id", "floors",
            "valid_from", "valid_to", "win_start_m", "win_end_m", "is_active"
        ]

    def validate_uid(self, value):
        return str(value).strip().upper()

    def validate(self, attrs):
        floors = attrs.get("floors", getattr(self.instance, "floors", None))
        start_m = attrs.get("win_start_m", getattr(self.instance, "win_start_m", 0))
        end_m = attrs.get("win_end_m", getattr(self.instance, "win_end_m", 1440))

        if floors:
            floor_list = parse_floors(floors)
            if any(f < 0 or f > 31 for f in floor_list):
                raise serializers.ValidationError({"floors": "Floors must be integers between 0 and 31."})

        if not (0 <= start_m <= 1440 and 0 <= end_m <= 1440 and start_m < end_m):
            raise serializers.ValidationError({"win_start_m": "win_start_m must be < win_end_m within range 0-1440."})

        return attrs

    def create(self, validated_data):
        # Employee bağlanmamış yeni bir kart varsayılan olarak erişim
        # açmamalı. Model tarafında `is_active` default'u True (assign/onboard
        # bunu bilerek set ettiği için True kalmalı) - o yüzden bu kısıtı
        # sadece burada uyguluyoruz: çağıran "is_active"ı açıkça göndermediyse
        # VE employee bağlamadıysa is_active=False'a zorla. Bu, düz
        # POST /api/cards yolu için eski server.js davranışını koruyor.
        if "is_active" not in self.initial_data and validated_data.get("employee") is None:
            validated_data["is_active"] = False
        return super().create(validated_data)


class CardOnboardSerializer(serializers.Serializer):
    """Eski /cards/add endpoint'i - employee ve kartı aynı anda oluşturur."""
    full_name = serializers.CharField(max_length=255)
    department = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    uid = serializers.CharField(max_length=50)
    floors = serializers.CharField(required=False, allow_blank=True, default="")
    valid_from = serializers.IntegerField(required=False, allow_null=True)
    valid_to = serializers.IntegerField(required=False, allow_null=True)
    win_start_m = serializers.IntegerField(default=0)
    win_end_m = serializers.IntegerField(default=1440)


class CardAssignSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(allow_null=True)
    is_active = serializers.BooleanField(required=False)
