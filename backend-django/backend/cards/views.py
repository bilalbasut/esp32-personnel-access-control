from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from cards.models import Card, Employee
from cards.serializers import (
    CardSerializer, EmployeeSerializer,
    CardOnboardSerializer, CardAssignSerializer
)
from core.acl import publish_acl_update


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all().order_by("ad_soyad")
    serializer_class = EmployeeSerializer


class CardViewSet(viewsets.ModelViewSet):
    queryset = Card.objects.select_related("employee").all().order_by("uid")
    serializer_class = CardSerializer
    lookup_field = "uid"

    def perform_create(self, serializer):
        card = serializer.save()
        if card.aktif == 1:
            publish_acl_update()

    def perform_update(self, serializer):
        card = serializer.save()
        publish_acl_update()

    def perform_destroy(self, instance):
        instance.delete()
        publish_acl_update()

    @action(detail=False, methods=["post"], url_path="add")
    def onboard(self, request):
        """Replaces legacy POST /cards/add (Creates employee + card in 1 atomic step)"""
        serializer = CardOnboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        uid = data["uid"].strip().upper()
        if Card.objects.filter(uid=uid).exists():
            return Response({"error": f"Card UID {uid} is already registered."}, status=status.HTTP_409_CONFLICT)

        with transaction.atomic():
            emp = Employee.objects.create(
                ad_soyad=data["ad_soyad"],
                departman=data.get("departman") or None
            )
            card = Card.objects.create(
                uid=uid,
                employee=emp,
                floors=data.get("floors", ""),
                valid_from=data.get("valid_from"),
                valid_to=data.get("valid_to"),
                win_start_m=data.get("win_start_m", 0),
                win_end_m=data.get("win_end_m", 1440),
                aktif=1
            )

        publish_acl_update()
        return Response({
            "message": f"Card {uid} registered for {emp.ad_soyad}.",
            "employee_id": emp.id,
            "uid": card.uid
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["put"], url_path="assign")
    def assign(self, request, uid=None):
        """Replaces PUT /cards/<uid>/assign"""
        card = self.get_object()
        serializer = CardAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        emp_id = serializer.validated_data["employee_id"]
        aktif_val = serializer.validated_data.get("aktif")

        if emp_id is not None:
            if not Employee.objects.filter(id=emp_id).exists():
                return Response({"error": "employee_id does not exist."}, status=status.HTTP_400_BAD_REQUEST)
            card.employee_id = emp_id
            card.aktif = 1 if aktif_val is None else (1 if aktif_val else 0)
        else:
            card.employee_id = None
            card.aktif = 0 if aktif_val is None else (1 if aktif_val else 0)

        card.save(update_fields=["employee_id", "aktif"])
        publish_acl_update()

        return Response({
            "message": f"Card {card.uid} {'linked' if emp_id else 'unlinked'}.",
            "card": {"uid": card.uid, "employee_id": card.employee_id, "aktif": card.aktif}
        })

    @action(detail=False, methods=["post"], url_path="revoke")
    def revoke(self, request):
        """Replaces legacy POST /cards/revoke"""
        uid = request.data.get("uid")
        if not uid:
            return Response({"error": "uid is required."}, status=status.HTTP_400_BAD_REQUEST)

        normalized_uid = str(uid).strip().upper()
        card = Card.objects.filter(uid=normalized_uid).first()
        if not card:
            return Response({"error": f"Card {normalized_uid} not found."}, status=status.HTTP_404_NOT_FOUND)

        card.aktif = 0
        card.save(update_fields=["aktif"])
        publish_acl_update()

        return Response({"message": f"Card {normalized_uid} revoked."})