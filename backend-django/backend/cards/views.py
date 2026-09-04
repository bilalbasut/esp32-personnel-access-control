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
    # perform_create/update/destroy artık elle yazılmıyor - AuditedModelViewSet
    # (core/audit_viewset.py) created_by/updated_by/deleted_by'ı set edip
    # alan-bazlı diff'i AuditLog'a otomatik yazıyor. instance.delete() hâlâ
    # soft-delete (bkz. core/models.py BaseModel) - bu employee'yi referans
    # alan access event'leri ve kart geçmişi, "yok olmuş" bir satıra işaret
    # etmek yerine hâlâ anlamlı/açıklanabilir kalıyor.
    queryset = Employee.objects.all().order_by("full_name")
    serializer_class = EmployeeSerializer

    def create(self, request, *args, **kwargs):
        """CardViewSet.create()'deki (bu dosyada yukarıda) AYNI kalıp,
        AYNI sebep - burada eksikti, testler yazılana kadar fark
        edilmemişti: employee_no unique=True (cards/models.py), ama bu
        view onu hiç yakalamıyordu, yani tekrarlı bir employee_no ham bir
        500'e düşerdi. Card zaten uid için bu korumaya sahipti; Employee'nin
        de aynısına ihtiyacı vardı.

        perform_create() burada, Card'ın AKSİNE, transaction.atomic()
        İÇİNE ALINDI - çünkü Employee'de geri alınmaması gereken bir yan
        etki (MQTT publish_acl_update()) yok, yani Card'daki gerekçe burada
        geçerli değil. Bu sarma kozmetik değil: IntegrityError'ı Python
        seviyesinde yakalamak, Postgres'in "bu transaction artık bozuk,
        rollback'e kadar yeni sorgu kabul etmiyorum" durumunu SİLMİYOR -
        ATOMIC_REQUESTS kapalı olduğu için normal prod isteğinde bu hiç
        görünmüyordu (autocommit tek başarısız INSERT'i kendi başına
        toparlıyor), ama TestCase'in her testi saran örtük atomic bloğunun
        İÇİNDEyken (python manage.py test'in her zaman yaptığı gibi)
        bozulma test'in geri kalanına sıçrıyordu: 409 yanıtının kendisi
        doğru dönüyordu ama testin bir SONRAKİ DB sorgusu (ör. satır
        sayısını doğrulamak) TransactionManagementError ile patlıyordu.
        atomic() burada bir SAVEPOINT açıp IntegrityError'da sadece o
        savepoint'e geri sarıyor, dış transaction'a dokunmuyor - onboard()'un
        (bu dosyada aşağıda) zaten aynı sebeple yaptığı şey."""
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
        """create()'deki aynı korumanın, aynı transaction.atomic()
        sarmalıyla birlikte, update (PATCH/PUT) tarafı - bir employee_no'yu
        ZATEN kayıtlı başka bir employee_no'ya değiştirmek de aynı şekilde
        ham bir IntegrityError/500 üretirdi (ve sarmalanmadan bırakılsaydı,
        aynı şekilde sonraki sorguları bozardı)."""
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
        """ModelViewSet.create()'i sadece tekrarlı UID'den gelen
        IntegrityError'ı ham bir 500 yerine temiz bir 409'a çevirmek için
        override ediyor. Bilinçli olarak transaction.atomic() İÇİNE
        ALINMADI: perform_create() ayrıca MQTT publish_acl_update() yan
        etkisini de tetikliyor; burada bir atomic blok, o ilgisiz MQTT
        çağrısı başarısız olursa zaten eklenmiş Card satırını geri alırdı.
        Tek bir Card.objects.create() zaten tek bir statement, yani
        autocommit tek başına IntegrityError'ı bu transaction'a dokunmadan
        yakalamaya yetiyor."""
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
        # created_by set etmek + audit log yazmak için AuditedModelViewSet'e
        # (core/audit_viewset.py) devrediyor, ardından ACL yayınını (bu
        # mixin'in bilmediği, karta özgü bir yan etki) elle tetikliyor.
        super().perform_create(serializer)
        if serializer.instance.is_active:
            publish_acl_update()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        publish_acl_update()

    def perform_destroy(self, instance):
        # AuditedModelViewSet.perform_destroy() instance.delete()'i çağırıyor
        # - bu da soft-delete yapıp ayrıca is_active=False'a çekiyor (bkz.
        # cards/models.py Card.delete()) - kartın uid'sini hâlâ referans alan
        # her şey için (access event, audit log) geçmişi koruyor, aynı anda
        # kartı ACL buffer'ından hemen düşürüyor.
        super().perform_destroy(instance)
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
        except IntegrityError:
            # Yukarıdaki ön-kontrol, aynı UID eşzamanlı onboard edilirse
            # race'e açık; asıl güvence DB'nin primary-key constraint'i.
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
