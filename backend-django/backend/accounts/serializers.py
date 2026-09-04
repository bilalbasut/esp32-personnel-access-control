from rest_framework import serializers

from accounts.models import Operator


class OperatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Operator
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "role", "phone", "is_staff", "is_superuser", "date_joined",
        ]
        read_only_fields = fields


class OperatorCreateSerializer(serializers.ModelSerializer):
    """Sadece OperatorViewSet.create() için - parola set_password() ile hash'lenir."""
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = Operator
        fields = ["id", "username", "password", "email", "first_name", "last_name", "role", "phone"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        operator = Operator(**validated_data)
        operator.set_password(password)
        operator.save()
        return operator
