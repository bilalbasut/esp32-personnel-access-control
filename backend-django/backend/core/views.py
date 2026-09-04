import os
import time
import hashlib
from datetime import datetime, timezone

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, FileResponse

from rest_framework import viewsets, status, mixins
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from core.audit_viewset import log_change, snapshot
from core.models import AccessEvent, Firmware
from core.serializers import (
    AccessEventSerializer,
    FirmwareSerializer,
    FirmwareUploadSerializer
)


class EventViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """En yeni 50 event, employee bilgisiyle. Sadece ListModelMixin (ReadOnly değil):
    get_queryset() RawQuerySet döner, .filter()/.get() desteklemez - detail route AttributeError verirdi."""
    serializer_class = AccessEventSerializer

    def get_queryset(self):
        sql = """
            SELECT a.*, e.full_name, e.department
            FROM access_events a
            LEFT JOIN cards c ON a.uid = c.uid
            LEFT JOIN employees e ON c.employee_id = e.id
            ORDER BY a.id DESC LIMIT 50
        """
        return AccessEvent.objects.raw(sql)


class FirmwareViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Firmware registry listelemesi, upload'lar ve ESP32 OTA için ham binary
    streaming'i yönetir.
    """
    queryset = Firmware.objects.all().order_by("-uploaded_at")
    serializer_class = FirmwareSerializer
    lookup_field = "version"
    lookup_value_regex = r"[^/]+"  # ÖNEMLİ: versiyon string'lerinde nokta olmasına izin verir (örn. 1.9.3)

    @action(
        detail=False,
        methods=["post"],
        url_path="upload",
        parser_classes=[MultiPartParser, FormParser]
    )
    def upload_binary(self, request):
        serializer = FirmwareUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        version = serializer.validated_data["version"]
        uploaded_file = serializer.validated_data["file"]

        if not uploaded_file.name.endswith(".bin"):
            return Response(
                {"error": "Only .bin firmware binaries are supported."},
                status=status.HTTP_400_BAD_REQUEST
            )

        content = uploaded_file.read()
        md5_hash = hashlib.md5(content).hexdigest()
        filename = f"firmware_{version}.bin"
        file_path = os.path.join(settings.FIRMWARE_DIR, filename)

        # Aynı version'a ikinci upload = update; created_by ezilmesin diye önce snapshot alınır.
        existing = Firmware.objects.filter(version=version).first()
        before = snapshot(existing) if existing else None
        is_new = existing is None

        user = request.user if getattr(request.user, "is_authenticated", False) else None

        with open(file_path, "wb") as destination:
            destination.write(content)

        firmware, created = Firmware.objects.update_or_create(
            version=version,
            defaults={
                "filename": filename,
                "md5": md5_hash,
                "size": len(content),
                "uploaded_at": int(time.time()),
                **({"created_by": user} if is_new else {"updated_by": user}),
            }
        )

        log_change(
            request, "firmware", "create" if created else "update", firmware,
            before=before
        )

        return Response(
            FirmwareSerializer(firmware).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="download", permission_classes=[AllowAny])
    def download(self, request, version=None):
        """Bilerek AllowAny: isteği atan ESP32'nin OTAUpdater'ı, JWT üretemez - global IsAuthenticated'a rağmen bu tek action açık."""
        firmware = self.get_object()
        file_path = os.path.join(settings.FIRMWARE_DIR, firmware.filename)

        if not os.path.isfile(file_path):
            return Response(
                {"error": f"Binary file '{firmware.filename}' not found on disk."},
                status=status.HTTP_404_NOT_FOUND
            )

        response = FileResponse(open(file_path, "rb"), content_type="application/octet-stream")
        response["Content-Length"] = os.path.getsize(file_path)
        return response


class PdksReportView(APIView):
    """
    GET /api/reports/pdks yerine geçer.
    Günlük ilk-giriş/son-çıkış toplamlarını üretir ve bölge (zone) sürelerini hesaplar.
    """
    def get(self, request):
        start_ts = request.query_params.get("start_ts")
        end_ts = request.query_params.get("end_ts")
        fmt = request.query_params.get("format")
        employee_id = request.query_params.get("employee_id")

        if not start_ts or not end_ts:
            return Response(
                {"error": "start_ts and end_ts (Unix timestamps) are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        emp_filter = None
        if employee_id not in (None, ""):
            try:
                emp_filter = int(employee_id)
            except ValueError:
                return Response(
                    {"error": "employee_id must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        sql = """
        -- Zone device_id ÖNEKİNDEN belirlenir: K3=ana giriş, K2=mola, K1=yemekhane. Yön a.dir'den gelir.
        WITH tagged_events AS (
            SELECT
                a.employee_id,
                CASE
                    WHEN a.device_id LIKE 'GATE-K3-%%' THEN 'MAIN'
                    WHEN a.device_id LIKE 'GATE-K2-%%' THEN 'BREAK_ROOM'
                    WHEN a.device_id LIKE 'GATE-K1-%%' THEN 'MESS_HALL'
                    ELSE 'MAIN'
                END AS zone,
                TO_CHAR(TO_TIMESTAMP(a.ts_utc) AT TIME ZONE %s, 'YYYY-MM-DD') AS working_date,
                a.ts_utc,
                a.dir,
                a.result
            FROM access_events a
            WHERE a.ts_utc >= %s AND a.ts_utc <= %s
              AND a.result IN (0, 4)  -- sadece granted(0) ve manual(4) - unknown/expired/schedule rapora hiç girmiyor
              AND (%s::int IS NULL OR a.employee_id = %s::int)
        ),
        event_pairs AS (
            SELECT
                employee_id, zone, working_date, ts_utc, dir,
                LEAD(ts_utc) OVER (PARTITION BY employee_id, zone, working_date ORDER BY ts_utc) AS next_ts,
                LEAD(dir) OVER (PARTITION BY employee_id, zone, working_date ORDER BY ts_utc) AS next_dir
            FROM tagged_events
        ),
        daily_zone_totals AS (
            SELECT
                employee_id,
                working_date,
                MIN(ts_utc) FILTER (WHERE zone = 'MAIN' AND dir = 0) AS first_in_main,
                MAX(ts_utc) FILTER (WHERE zone = 'MAIN' AND dir = 1) AS last_out_main,
                COALESCE(SUM(next_ts - ts_utc) FILTER (
                    WHERE zone = 'MAIN' AND dir = 0 AND next_dir = 1
                ), 0) AS total_work_seconds,
                COALESCE(SUM(next_ts - ts_utc) FILTER (
                    WHERE zone = 'MESS_HALL' AND dir = 0 AND next_dir = 1
                ), 0) AS yemek_molasi_seconds,
                COALESCE(SUM(next_ts - ts_utc) FILTER (
                    WHERE zone = 'BREAK_ROOM' AND dir = 0 AND next_dir = 1
                ), 0) AS mola_seconds
            FROM event_pairs
            GROUP BY employee_id, working_date
        )
        SELECT
            e.id AS employee_id, e.full_name, e.department, z.working_date,
            z.first_in_main, z.last_out_main, z.total_work_seconds,
            z.yemek_molasi_seconds, z.mola_seconds
        FROM daily_zone_totals z
        JOIN employees e ON z.employee_id = e.id
        ORDER BY z.working_date DESC, e.full_name ASC;
        """

        report_tz = getattr(settings, "REPORT_TZ", "Europe/Istanbul")
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, [report_tz, start_ts, end_ts, emp_filter, emp_filter])
                cols = [c[0] for c in cursor.description]
                rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as err:
            return Response({"error": str(err)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if fmt == "csv":
            return self._generate_csv(rows)

        return Response(rows)

    def _generate_csv(self, rows):
        def format_dur(sec):
            if not sec or sec < 0:
                return "00:00:00"
            h, rem = divmod(int(sec), 3600)
            m, s = divmod(rem, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        def csv_escape(v):
            if v is None:
                return '""'
            escaped = str(v).replace('"', '""')
            return f'"{escaped}"'

        header = "Personel No,Ad Soyad,Departman,Tarih,İlk Giriş,Son Çıkış,Toplam Çalışma Süresi,Yemek Molası,Mola\n"
        lines = []
        for r in rows:
            fin = datetime.fromtimestamp(r["first_in_main"], tz=timezone.utc).strftime("%H:%M:%S") if r["first_in_main"] else ""
            lout = datetime.fromtimestamp(r["last_out_main"], tz=timezone.utc).strftime("%H:%M:%S") if r["last_out_main"] else ""
            fields = [
                r["employee_id"], r["full_name"], r["department"], r["working_date"],
                fin, lout,
                format_dur(r["total_work_seconds"]),
                format_dur(r["yemek_molasi_seconds"]),
                format_dur(r["mola_seconds"])
            ]
            lines.append(",".join(csv_escape(f) for f in fields))

        csv_content = header + "\n".join(lines)
        res = HttpResponse(csv_content, content_type="text/csv; charset=utf-8")
        res["Content-Disposition"] = 'attachment; filename="pdks_raporu.csv"'
        return res