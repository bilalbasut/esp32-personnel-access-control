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
