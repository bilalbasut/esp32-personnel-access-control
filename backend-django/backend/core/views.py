import hashlib
import itertools
import json
import os
import re
import time
from datetime import datetime, timezone

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core import mqtt_utils
from core.acl import parse_floors, publish_acl_update
from core.models import AccessEvent, Card, Device, Employee, Firmware

VALID_COMMANDS = {"open", "sync", "reboot", "settime"}
VERSION_RE = re.compile(r"^[a-zA-Z0-9._-]{1,50}$")

# In-memory monotonic command sequence counter, seeded from current second -
# same behavior as server.js's `let serverCmdSeq = Math.floor(Date.now()/1000)`,
# including the "resets on process restart" quirk.
_cmd_seq_counter = itertools.count(int(time.time()) + 1)


def _now():
    return int(time.time())


def _body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _format_window(start_m, end_m):
    s = start_m if isinstance(start_m, (int, float)) else 0
    e = end_m if isinstance(end_m, (int, float)) else 1440
    e_display = 1439 if e == 1440 else e

    def to_hhmm(mins):
        return f"{int(mins // 60) % 24:02d}:{int(mins % 60):02d}"

    return f"{to_hhmm(s)}-{to_hhmm(e_display)}"


def _validate_floors_and_window(floors, window_start, window_end):
    # Firmware stores floor numbers in a 32-bit bitmask and silently drops
    # any floor >= 32 - reject bad input here rather than let it fail
    # invisibly on-device.
    floor_list = parse_floors(floors)
    if any(f < 0 or f > 31 for f in floor_list):
        return "floors must be between 0 and 31."
    if (
        window_start < 0 or window_start > 1440
        or window_end < 0 or window_end > 1440
        or window_start >= window_end
    ):
        return "win_start_m must be less than win_end_m, both within 0-1440."
    return None


def _format_duration(sec):
    if not sec or sec < 0:
        return "00:00:00"
    hrs, rem = divmod(int(sec), 3600)
    mins, secs = divmod(rem, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def _csv_field(value):
    if value is None:
        return ""
    return '"' + str(value).replace('"', '""') + '"'


def _floors_to_store(floors):
    if isinstance(floors, list):
        return ",".join(str(f) for f in floors)
    return floors or ""


# --- GET: Live Feed of Door Scans ---
@require_http_methods(["GET"])
def events_list(request):
    events = list(AccessEvent.objects.order_by("-id")[:50].values())

    # Mirrors the original's LIVE join (access_events.uid -> cards.uid ->
    # employees), not a snapshot of access_events.employee_id - that field is
    # only ever set once at insert time by the collector, so if a card gets
    # reassigned to a different employee later, historical events should
    # still show whoever currently holds the card, matching prior behavior.
    uids = {e["uid"] for e in events if e["uid"]}
    card_to_employee = dict(Card.objects.filter(uid__in=uids).values_list("uid", "employee_id"))
    employee_ids = {eid for eid in card_to_employee.values() if eid is not None}
    employees = {
        emp["id"]: emp
        for emp in Employee.objects.filter(id__in=employee_ids).values("id", "ad_soyad", "departman")
    }
    for e in events:
        emp = employees.get(card_to_employee.get(e["uid"]))
        e["ad_soyad"] = emp["ad_soyad"] if emp else None
        e["departman"] = emp["departman"] if emp else None
    return JsonResponse(events, safe=False)


# --- GET: Device Fleet Status ---
@require_http_methods(["GET"])
def devices_list(request):
    devices = Device.objects.all().order_by("id").values()
    return JsonResponse(list(devices), safe=False)


# --- GET /api/cards + POST /api/cards share one path, like Express's
# separate app.get/app.post registrations on the same route. ---
@csrf_exempt
@require_http_methods(["GET", "POST"])
def cards_collection(request):
    if request.method == "POST":
        return cards_create(request)
    return cards_list(request)


def cards_list(request):
    cards = Card.objects.select_related("employee").order_by("employee__ad_soyad")
    rows = [
        {
            "uid": c.uid,
            "floors": c.floors,
            "valid_from": c.valid_from,
            "valid_to": c.valid_to,
            "win_start_m": c.win_start_m,
            "win_end_m": c.win_end_m,
            "aktif": c.aktif,
            "employee_id": c.employee_id,
            "ad_soyad": c.employee.ad_soyad if c.employee_id else None,
            "departman": c.employee.departman if c.employee_id else None,
        }
        for c in cards
    ]
    return JsonResponse(rows, safe=False)


# --- GET /api/employees + POST /api/employees share one path. ---
@csrf_exempt
@require_http_methods(["GET", "POST"])
def employees_collection(request):
    if request.method == "POST":
        return employees_create(request)
    return employees_list(request)


def employees_list(request):
    employees = Employee.objects.prefetch_related("cards").order_by("ad_soyad")
    rows = []
    for emp in employees:
        cards = list(emp.cards.all())
        base = {"id": emp.id, "ad_soyad": emp.ad_soyad, "departman": emp.departman, "aktif": emp.aktif}
        if cards:
            rows.extend({**base, "card_uid": c.uid} for c in cards)
        else:
            rows.append({**base, "card_uid": None})
    return JsonResponse(rows, safe=False)


# --- POST: Create an employee with no card yet ---
@csrf_exempt
@require_http_methods(["POST"])
def employees_create(request):
    body = _body(request)
    ad_soyad = body.get("ad_soyad")
    departman = body.get("departman")
    if not ad_soyad:
        return JsonResponse({"error": "ad_soyad is required."}, status=400)

    emp = Employee.objects.create(ad_soyad=ad_soyad, departman=departman or None)
    return JsonResponse(
        {"id": emp.id, "ad_soyad": emp.ad_soyad, "departman": emp.departman, "aktif": emp.aktif}
    )


# --- POST: Register a physical card, optionally unassigned ---
@csrf_exempt
@require_http_methods(["POST"])
def cards_create(request):
    body = _body(request)
    uid = body.get("uid")
    employee_id = body.get("employee_id")
    floors = body.get("floors")
    valid_from = body.get("valid_from")
    valid_to = body.get("valid_to")
    win_start_m = body.get("win_start_m")
    win_end_m = body.get("win_end_m")
    aktif = body.get("aktif")

    if not uid:
        return JsonResponse({"error": "uid is required."}, status=400)

    normalized_uid = str(uid).strip().upper()
    window_start = win_start_m if isinstance(win_start_m, (int, float)) else 0
    window_end = win_end_m if isinstance(win_end_m, (int, float)) else 1440
    normalized_employee_id = employee_id if isinstance(employee_id, int) else None
    if aktif is not None:
        card_aktif = 1 if aktif else 0
    else:
        card_aktif = 1 if normalized_employee_id is not None else 0

    validation_error = _validate_floors_and_window(floors, window_start, window_end)
    if validation_error:
        return JsonResponse({"error": validation_error}, status=400)

    if normalized_employee_id is not None and not Employee.objects.filter(id=normalized_employee_id).exists():
        return JsonResponse({"error": "employee_id does not exist."}, status=400)

    try:
        Card.objects.create(
            uid=normalized_uid,
            employee_id=normalized_employee_id,
            floors=_floors_to_store(floors),
            valid_from=valid_from or None,
            valid_to=valid_to or None,
            win_start_m=window_start,
            win_end_m=window_end,
            aktif=card_aktif,
        )
    except IntegrityError:
        return JsonResponse({"error": f"Card UID {normalized_uid} is already registered."}, status=409)

    if card_aktif == 1:
        publish_acl_update()

    return JsonResponse({"message": f"Card {normalized_uid} registered.", "aktif": card_aktif})


# --- PUT: Link (or unlink) a card to/from an employee ---
@csrf_exempt
@require_http_methods(["PUT"])
def cards_assign(request, uid):
    normalized_uid = str(uid).strip().upper()
    body = _body(request)
    employee_id = body.get("employee_id")

    if employee_id is not None and not isinstance(employee_id, int):
        return JsonResponse({"error": "employee_id must be an integer, or null to unlink."}, status=400)

    new_employee_id = employee_id
    if "aktif" in body:
        aktif = 1 if body.get("aktif") else 0
    else:
        aktif = 1 if new_employee_id is not None else 0

    try:
        card = Card.objects.get(uid=normalized_uid)
    except Card.DoesNotExist:
        return JsonResponse({"error": f"Card UID {normalized_uid} not found."}, status=404)

    if new_employee_id is not None and not Employee.objects.filter(id=new_employee_id).exists():
        return JsonResponse({"error": "employee_id does not exist."}, status=400)

    card.employee_id = new_employee_id
    card.aktif = aktif
    card.save(update_fields=["employee_id", "aktif"])

    # aktif may have changed as a side effect of (un)linking, and that DOES
    # reach the device - republish either way, cheap and correct even when
    # aktif didn't actually change.
    publish_acl_update()

    return JsonResponse({
        "message": f"Card {normalized_uid} {'linked' if new_employee_id is not None else 'unlinked'}.",
        "card": {"uid": card.uid, "employee_id": card.employee_id, "aktif": card.aktif},
    })


# --- GET: Date-range PDKS Report with optional CSV export ---
@require_http_methods(["GET"])
def reports_pdks(request):
    start_ts = request.GET.get("start_ts")
    end_ts = request.GET.get("end_ts")
    fmt = request.GET.get("format")
    employee_id = request.GET.get("employee_id")

    if not start_ts or not end_ts:
        return JsonResponse({"error": "start_ts and end_ts (Unix timestamps) are required."}, status=400)

    employee_id_filter = None
    if employee_id not in (None, ""):
        try:
            employee_id_filter = int(employee_id)
        except ValueError:
            return JsonResponse({"error": "employee_id must be an integer."}, status=400)

    sql = """
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
              AND a.result IN (0, 4)
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
            e.id AS employee_id, e.ad_soyad, e.departman, z.working_date,
            z.first_in_main, z.last_out_main, z.total_work_seconds,
            z.yemek_molasi_seconds, z.mola_seconds
        FROM daily_zone_totals z
        JOIN employees e ON z.employee_id = e.id
        ORDER BY z.working_date DESC, e.ad_soyad ASC;
    """

    report_tz = settings.REPORT_TZ
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [report_tz, start_ts, end_ts, employee_id_filter, employee_id_filter],
            )
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as err:
        return JsonResponse({"error": str(err)}, status=500)

    if fmt == "csv":
        header = "Personel No,Ad Soyad,Departman,Tarih,İlk Giriş,Son Çıkış,Toplam Çalışma Süresi,Yemek Molası,Mola\n"
        lines = []
        for r in rows:
            first_in = (
                datetime.fromtimestamp(r["first_in_main"], tz=timezone.utc).strftime("%H:%M:%S")
                if r["first_in_main"] else ""
            )
            last_out = (
                datetime.fromtimestamp(r["last_out_main"], tz=timezone.utc).strftime("%H:%M:%S")
                if r["last_out_main"] else ""
            )
            fields = [
                r["employee_id"], r["ad_soyad"], r["departman"], r["working_date"],
                first_in, last_out,
                _format_duration(r["total_work_seconds"]),
                _format_duration(r["yemek_molasi_seconds"]),
                _format_duration(r["mola_seconds"]),
            ]
            lines.append(",".join(_csv_field(f) for f in fields))
        csv_body = header + "\n".join(lines)
        response = HttpResponse(csv_body, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="pdks_raporu.csv"'
        return response

    return JsonResponse(rows, safe=False)


# --- POST: Onboard a New Employee & Card (transactional) ---
@csrf_exempt
@require_http_methods(["POST"])
def cards_add(request):
    body = _body(request)
    ad_soyad = body.get("ad_soyad")
    departman = body.get("departman")
    uid = body.get("uid")
    floors = body.get("floors")
    valid_from = body.get("valid_from")
    valid_to = body.get("valid_to")
    win_start_m = body.get("win_start_m")
    win_end_m = body.get("win_end_m")

    if not ad_soyad or not uid:
        return JsonResponse({"error": "ad_soyad and uid are required."}, status=400)

    # ESP32 always sends UID as uppercase hex with no separators - the
    # stored value must match that exactly or the card will never be found.
    normalized_uid = str(uid).strip().upper()
    floors_to_store = _floors_to_store(floors)
    window_start = win_start_m if isinstance(win_start_m, (int, float)) else 0
    window_end = win_end_m if isinstance(win_end_m, (int, float)) else 1440

    validation_error = _validate_floors_and_window(floors, window_start, window_end)
    if validation_error:
        return JsonResponse({"error": validation_error}, status=400)

    try:
        with transaction.atomic():
            emp = Employee.objects.create(ad_soyad=ad_soyad, departman=departman)
            try:
                Card.objects.create(
                    uid=normalized_uid,
                    employee_id=emp.id,
                    floors=floors_to_store,
                    valid_from=valid_from or None,
                    valid_to=valid_to or None,
                    win_start_m=window_start,
                    win_end_m=window_end,
                )
            except IntegrityError:
                # uid is the PRIMARY KEY on cards - duplicate card, not a
                # server fault. A previously revoked card can't be
                # re-added through this endpoint yet (upsert/reactivation
                # is a separate policy decision), so surface this clearly
                # instead of a generic 500.
                return JsonResponse(
                    {"error": f"Card UID {normalized_uid} is already registered."}, status=409
                )
    except IntegrityError as err:
        return JsonResponse({"error": f"Database transaction failed: {err}"}, status=500)

    # Step 3: Automatically trigger the hardware synchronization
    publish_acl_update()

    return JsonResponse({"message": "Employee added and hardware updated successfully."})


# --- POST: Revoke a Card (Instantly blocks access) ---
@csrf_exempt
@require_http_methods(["POST"])
def cards_revoke(request):
    body = _body(request)
    uid = body.get("uid")
    if not uid:
        return JsonResponse({"error": "uid is required."}, status=400)
    normalized_uid = str(uid).strip().upper()

    Card.objects.filter(uid=normalized_uid).update(aktif=0)
    publish_acl_update()

    return JsonResponse({"message": "Card revoked and hardware updated."})


# --- DELETE: Permanently remove a card record ---
@csrf_exempt
@require_http_methods(["DELETE"])
def cards_delete(request, uid):
    normalized_uid = str(uid).strip().upper()
    deleted, _ = Card.objects.filter(uid=normalized_uid).delete()
    if deleted == 0:
        return JsonResponse({"error": f"Card UID {normalized_uid} not found."}, status=404)

    # The deleted card might still have been active if someone deletes
    # without revoking first - refresh the ACL so the device's retained
    # list matches reality either way.
    publish_acl_update()

    return JsonResponse({"message": f"Card UID {normalized_uid} deleted."})


# --- POST: Send remote command to ESP32 ---
@csrf_exempt
@require_http_methods(["POST"])
def devices_command(request, device_id):
    body = _body(request)
    cmd = body.get("cmd")
    ts = body.get("ts")

    if cmd not in VALID_COMMANDS:
        return JsonResponse({"error": "Invalid command."}, status=400)

    now = _now()
    seq = next(_cmd_seq_counter)
    cmd_topic = f"pdks/merkez/dev/{device_id}/cmd"

    payload_obj = {"seq": seq, "cmd": cmd, "ts": now, "params": {}}
    if cmd == "settime":
        payload_obj["params"]["ts"] = ts if isinstance(ts, int) else now

    try:
        mqtt_utils.publish(cmd_topic, json.dumps(payload_obj), qos=1)
    except Exception as err:
        return JsonResponse({"error": f"Failed to send command: {err}"}, status=500)

    return JsonResponse({"message": f"Command '{cmd}' queued for device {device_id}.", "seq": seq})


# --- POST: Upload a firmware binary ---
@csrf_exempt
@require_http_methods(["POST"])
def firmware_upload(request):
    version = request.GET.get("version")
    # The version becomes part of a filename written to disk - restrict it
    # to a safe charset so it can't be used for path traversal.
    if not version or not VERSION_RE.match(version):
        return JsonResponse(
            {"error": "version query param is required (alphanumeric, dot, dash, underscore only)."},
            status=400,
        )

    body = request.body
    if not body:
        return JsonResponse(
            {"error": "Request body must be the raw firmware binary (application/octet-stream)."},
            status=400,
        )

    filename = f"{version}.bin"
    md5 = hashlib.md5(body).hexdigest()
    size = len(body)
    now = _now()

    try:
        with open(os.path.join(settings.FIRMWARE_DIR, filename), "wb") as f:
            f.write(body)
        Firmware.objects.update_or_create(
            version=version,
            defaults={"filename": filename, "md5": md5, "size": size, "uploaded_at": now},
        )
    except Exception as err:
        return JsonResponse({"error": str(err)}, status=500)

    return JsonResponse({"message": f"Firmware {version} uploaded.", "version": version, "md5": md5, "size": size})


# --- GET: List uploaded firmware versions ---
@require_http_methods(["GET"])
def firmware_list(request):
    rows = list(
        Firmware.objects.all().order_by("-uploaded_at").values("version", "filename", "md5", "size", "uploaded_at")
    )
    return JsonResponse(rows, safe=False)


# --- POST: Trigger an OTA update on a specific device for an uploaded version ---
@csrf_exempt
@require_http_methods(["POST"])
def devices_ota(request, device_id):
    body = _body(request)
    version = body.get("version")

    if not version:
        return JsonResponse({"error": "version is required."}, status=400)

    panel_base_url = settings.PANEL_BASE_URL
    if not panel_base_url:
        return JsonResponse(
            {
                "error": (
                    "PANEL_BASE_URL is not configured - set it in .env to this "
                    "server's LAN-reachable address (e.g. http://192.168.11.66:3000), "
                    "since the device cannot resolve \"localhost\"."
                )
            },
            status=500,
        )

    try:
        fw = Firmware.objects.get(version=version)
    except Firmware.DoesNotExist:
        return JsonResponse({"error": f"Firmware version {version} has not been uploaded."}, status=404)

    url = f"{panel_base_url.rstrip('/')}/firmware/{fw.filename}"
    cmd_topic = f"pdks/merkez/dev/{device_id}/cmd"
    cmd_payload = json.dumps({"cmd": "ota", "url": url, "md5": fw.md5, "size": fw.size})

    try:
        mqtt_utils.publish(cmd_topic, cmd_payload, qos=1)
    except Exception as err:
        return JsonResponse({"error": f"Failed to send OTA command: {err}"}, status=500)

    return JsonResponse({"message": f"OTA to version {version} queued for device {device_id}.", "url": url})
