from django.db import IntegrityError, transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.audit import log_action
from cards.models import Card, Employee
from cards.serializers import (
    CardSerializer, EmployeeSerializer,
    CardOnboardSerializer, CardAssignSerializer
)
from core.acl import publish_acl_update
from core.audit_viewset import AuditedModelViewSet


class EmployeeViewSet(AuditedModelViewSet, viewsets.ModelViewSet):
    queryset = Employee.objects.all().order_by("full_name")
    serializer_class = EmployeeSerializer

    def create(self, request, *args, **kwargs):
        """IntegrityError -> 409, Card'ın deseniyle aynı. atomic() sarmalı gerekli:
        yakalasak da IntegrityError transaction'ı bozar, sonraki sorgular patlar (Card'da
        MQTT yan etkisi olduğu için bu sarma yok, burada güvenli)."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                self.perform_create(serializer)
        except IntegrityError:
            employee_no = serializer.validated_data.get("employee_no")
            return Response(
                {"error": f"Employee No {employee_no} is already registered."},
                status=status.HTTP_409_CONFLICT
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        """create()'deki aynı 409 koruması, update tarafı."""
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except IntegrityError:
            employee_no = request.data.get("employee_no")
            return Response(
                {"error": f"Employee No {employee_no} is already registered."},
                status=status.HTTP_409_CONFLICT
            )


class CardViewSet(AuditedModelViewSet, viewsets.ModelViewSet):
    queryset = Card.objects.select_related("employee").all().order_by("uid")
    serializer_class = CardSerializer
    lookup_field = "uid"

    def create(self, request, *args, **kwargs):
        """Tekrarlı UID -> 409. Bilerek atomic() içine alınmadı: perform_create()
        MQTT publish_acl_update() de tetikliyor, atomic olsaydı MQTT hatası zaten eklenmiş Card'ı geri alırdı."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError:
            uid = serializer.validated_data.get("uid")
            return Response(
                {"error": f"Card UID {uid} is already registered."},
                status=status.HTTP_409_CONFLICT
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        super().perform_create(serializer)
        if serializer.instance.is_active:
            publish_acl_update()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        publish_acl_update()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)  # soft-delete + is_active=False (Card.delete())
        publish_acl_update()

    @action(detail=False, methods=["post"], url_path="add")
    def onboard(self, request):
        """Eski POST /cards/add yerine geçiyor (employee + kartı tek atomic adımda oluşturur)"""
        serializer = CardOnboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        uid = data["uid"].strip().upper()
        if Card.objects.filter(uid=uid).exists():
            return Response({"error": f"Card UID {uid} is already registered."}, status=status.HTTP_409_CONFLICT)

        try:
            with transaction.atomic():
                emp = Employee.objects.create(
                    full_name=data["full_name"],
                    department=data.get("department") or None
                )
                card = Card.objects.create(
                    uid=uid,
                    employee=emp,
                    floors=data.get("floors", ""),
                    valid_from=data.get("valid_from"),
                    valid_to=data.get("valid_to"),
                    win_start_m=data.get("win_start_m", 0),
                    win_end_m=data.get("win_end_m", 1440),
                    is_active=True
                )
        except IntegrityError:  # ön-kontrol race'e açık, asıl güvence PK constraint
            return Response({"error": f"Card UID {uid} is already registered."}, status=status.HTTP_409_CONFLICT)

        log_action(
            request, "card.onboard", f"Card {uid} / Employee {emp.full_name} (#{emp.id})",
            details={"uid": uid, "employee_id": emp.id}
        )
        publish_acl_update()
        return Response({
            "message": f"Card {uid} registered for {emp.full_name}.",
            "employee_id": emp.id,
            "uid": card.uid
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["put"], url_path="assign")
    def assign(self, request, uid=None):
        """PUT /cards/<uid>/assign yerine geçiyor"""
        card = self.get_object()
        serializer = CardAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        emp_id = serializer.validated_data["employee_id"]
        is_active_val = serializer.validated_data.get("is_active")

        if emp_id is not None:
            if not Employee.objects.filter(id=emp_id).exists():
                return Response({"error": "employee_id does not exist."}, status=status.HTTP_400_BAD_REQUEST)
            card.employee_id = emp_id
            card.is_active = True if is_active_val is None else bool(is_active_val)
        else:
            card.employee_id = None
            card.is_active = False if is_active_val is None else bool(is_active_val)

        card.save(update_fields=["employee_id", "is_active"])
        log_action(
            request, "card.assign", f"Card {card.uid}",
            details={"employee_id": card.employee_id, "is_active": card.is_active}
        )
        publish_acl_update()

        return Response({
            "message": f"Card {card.uid} {'linked' if emp_id else 'unlinked'}.",
            "card": {"uid": card.uid, "employee_id": card.employee_id, "is_active": card.is_active}
        })

    @action(detail=False, methods=["post"], url_path="revoke")
    def revoke(self, request):
        """Eski POST /cards/revoke yerine geçiyor"""
        uid = request.data.get("uid")
        if not uid:
            return Response({"error": "uid is required."}, status=status.HTTP_400_BAD_REQUEST)

        normalized_uid = str(uid).strip().upper()
        card = Card.objects.filter(uid=normalized_uid).first()
        if not card:
            return Response({"error": f"Card {normalized_uid} not found."}, status=status.HTTP_404_NOT_FOUND)

        card.is_active = False
        card.save(update_fields=["is_active"])
        log_action(request, "card.revoke", f"Card {normalized_uid}")
        publish_acl_update()

        return Response({"message": f"Card {normalized_uid} revoked."})
