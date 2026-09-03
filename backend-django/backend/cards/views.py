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


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all().order_by("full_name")
    serializer_class = EmployeeSerializer

    def perform_create(self, serializer):
        employee = serializer.save()
        log_action(self.request, "employee.create", f"Employee {employee.full_name} (#{employee.id})")

    def perform_update(self, serializer):
        employee = serializer.save()
        log_action(self.request, "employee.update", f"Employee {employee.full_name} (#{employee.id})")

    def perform_destroy(self, instance):
        # instance.delete() soft-deletes - see SoftDeletableModel in
        # core/models.py. Access events and card history that reference
        # this employee stay explainable instead of pointing at a row
        # that's simply gone.
        instance.delete()
        log_action(self.request, "employee.delete", f"Employee {instance.full_name} (#{instance.id})")


class CardViewSet(viewsets.ModelViewSet):
    queryset = Card.objects.select_related("employee").all().order_by("uid")
    serializer_class = CardSerializer
    lookup_field = "uid"

    def create(self, request, *args, **kwargs):
        """Overrides ModelViewSet.create() only to turn a duplicate-UID
        IntegrityError into a clean 409 instead of an unhandled 500.
        Deliberately NOT wrapped in transaction.atomic(): perform_create()
        also fires the MQTT publish_acl_update() side effect, and an atomic
        block here would roll back an already-inserted Card row if that
        unrelated MQTT call happened to fail. A single Card.objects.create()
        is already one statement, so autocommit alone is enough to catch
        its IntegrityError cleanly without touching that transaction."""
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
        card = serializer.save()
        log_action(self.request, "card.create", f"Card {card.uid}")
        if card.is_active:
            publish_acl_update()

    def perform_update(self, serializer):
        card = serializer.save()
        log_action(self.request, "card.update", f"Card {card.uid}")
        publish_acl_update()

    def perform_destroy(self, instance):
        # instance.delete() soft-deletes and also sets is_active=False (see
        # Card.delete() in cards/models.py) - preserves the card's history
        # for anything that still references its uid (access events, audit
        # log), while immediately pulling it out of the ACL buffer.
        instance.delete()
        log_action(self.request, "card.delete", f"Card {instance.uid}")
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
        except IntegrityError:
            # Pre-check above is racy under concurrent onboarding of the same
            # UID; the DB's primary-key constraint is the real guard.
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
        """Replaces PUT /cards/<uid>/assign"""
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
        """Replaces legacy POST /cards/revoke"""
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
