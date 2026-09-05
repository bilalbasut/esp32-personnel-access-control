# PDKS Backend

*This document is written primarily in Turkish. An English translation is included at the end of this file — jump to [English Version](#english-version).*

---

# PDKS Backend

Django REST Framework tabanlı API, PostgreSQL veritabanı, bağımsız bir Python MQTT toplayıcı servisi ve Eclipse Mosquitto broker'ından oluşur. ESP32 kapı üniteleri MQTT üzerinden toplayıcıya, web paneli ise bu API'ye HTTP/JWT üzerinden konuşur.

Donanım/firmware detayları için repo kökündeki ana `README.md` dosyasına bakın.

## İçindekiler

1. [Servisler ve Mimari](#1-servisler-ve-mimari)
2. [Kurulum](#2-kurulum)
3. [Ortam Değişkenleri](#3-ortam-değişkenleri)
4. [Proje Yapısı (Django Uygulamaları)](#4-proje-yapısı-django-uygulamaları)
5. [Kimlik Doğrulama ve Roller](#5-kimlik-doğrulama-ve-roller)
6. [API Uç Noktaları](#6-api-uç-noktaları)
7. [Veri Modeli](#7-veri-modeli)
8. [MQTT Toplayıcı Servis (collector.py)](#8-mqtt-toplayıcı-servis-collectorpy)
9. [Testler](#9-testler)
10. [Bilinen Sınırlamalar](#10-bilinen-sınırlamalar)

## 1. Servisler ve Mimari

```
ESP32 kapı üniteleri ──MQTT (QoS1)──> Mosquitto ──> collector.py ──raw SQL──> PostgreSQL <──ORM── Django API <──JWT/HTTP── Vue paneli
```

`docker-compose.yml` dört servis tanımlar:

| Servis | Görüntü/Build | Port | Görev |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5433→5432 | Veritabanı |
| `mosquitto` | `eclipse-mosquitto:2` | 1883, 9001 | MQTT broker (TLS/kimlik doğrulama yok, bkz. §10) |
| `backend` | `./backend` | 3000 | Django REST API (bu doküman) |
| `collector` | `./collector` | — | Bağımsız Python servisi, MQTT'den dinleyip veritabanına yazar |

Backend ve collector birbirinden bağımsız süreçlerdir; backend'in Django ORM'i normal CRUD işlemlerini yönetirken, collector cihazlardan gelen yüksek frekanslı olay/heartbeat trafiğini ham SQL ile (ORM ek yükü olmadan) doğrudan yazar.

## 2. Kurulum

### Docker ile (önerilen)

```bash
cd backend-django
cp .env.example .env   # değerleri kendi ortamınıza göre düzenleyin, bkz. §3
docker compose up -d --build
```

Backend konteyneri açılışta otomatik `python manage.py migrate` çalıştırır. İlk operatör hesabını oluşturmak için:

```bash
docker compose exec backend python manage.py createsuperuser
```

### Docker'sız (lokal geliştirme)

```bash
cd backend-django/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:3000
```

PostgreSQL ve Mosquitto'nun ayrıca çalışıyor olması gerekir (`.env`'deki `DB_HOST`/`MQTT_HOST` değerlerini `127.0.0.1` bırakabilirsiniz).

Toplayıcı servisi ayrı çalıştırmak için:

```bash
cd backend-django/collector
pip install -r requirements.txt
python collector.py
```

## 3. Ortam Değişkenleri

`.env.example` dosyasından kopyalanır:

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_PORT` / `DB_HOST` | `pdks` / `pdks` / `pdks_password` / `5432` / `127.0.0.1` | PostgreSQL bağlantısı. Docker Compose içinde `DB_HOST` otomatik `postgres`'e ezilir. |
| `MQTT_HOST` / `MQTT_PORT` | `127.0.0.1` / `1883` | Broker adresi. Docker Compose içinde `MQTT_HOST` otomatik `mosquitto`'ya ezilir. |
| `DJANGO_SECRET_KEY` | `change-me-in-production` | **Prod'a çıkmadan önce değiştirilmeli.** |
| `DJANGO_DEBUG` | `1` | Prod'da `0` yapılmalı. |
| `DJANGO_ALLOWED_HOSTS` | `*` | Virgülle ayrılmış host listesi. |
| `PORT` | `3000` | Django'nun dinlediği port. |
| `PANEL_BASE_URL` | — | ESP32'lerin OTA indirmesi için kullandığı, **LAN'dan erişilebilir** adres — `localhost` OLMAMALI, ESP32 bunu çözemez. |
| `TZ_OFFSET_MINUTES` | `180` | ACL'deki saat pencerelerinin yerel (TR) saatten UTC'ye çevrilmesinde kullanılır (`core/acl.py`). |
| `REPORT_TZ` | `Europe/Istanbul` | PDKS raporundaki gün sınırlarının hesaplandığı saat dilimi. |

## 4. Proje Yapısı (Django Uygulamaları)

| Uygulama | İçerik |
|---|---|
| `core` | Ortak `BaseModel`, audit-log altyapısı (`AuditedModelViewSet`), `AccessEvent`/`Firmware` modelleri, olay listesi + PDKS raporu + firmware upload/download view'ları, ACL binary üretimi (`acl.py`), MQTT yardımcıları (`mqtt_utils.py`) |
| `accounts` | `Operator` kullanıcı modeli, JWT login/refresh/logout/me view'ları, `AuditLog` modeli, admin-only operatör yönetimi |
| `cards` | `Employee` ve `Card` modelleri, kart onboard/assign/revoke özel action'ları |
| `devices` | `Device` modeli, cihaza komut gönderme (`command`) ve OTA tetikleme (`ota`) action'ları |
| `config` | Django ayarları ve URL yönlendirmesi |

## 5. Kimlik Doğrulama ve Roller

**JWT** (`djangorestframework-simplejwt`): access token 15 dakika, refresh token 7 gün, rotate + blacklist-on-refresh aktif (çalıntı bir refresh token sonsuza kadar tekrar kullanılamaz). Token'lar `localStorage`'da tutulur (panel yalnızca güvenilir bir iç ağdan kullanıldığı için httpOnly cookie/CSRF karmaşıklığına girilmedi).

`DEFAULT_PERMISSION_CLASSES` proje genelinde `IsAuthenticated` — tek istisna `FirmwareViewSet.download` (ESP32'nin OTA indirmesi, JWT üretemez, bilerek `AllowAny`).

**Roller:** `Operator.role`, `admin` veya `operator` (varsayılan `operator`). Bugün itibarıyla tek fark: **operatör hesabı oluşturma** (`/operators` sayfası, panelde yalnızca adminlere görünür; backend'de `accounts/permissions.py`'deki `IsAdmin` ile korunur — admin olmayan biri endpoint'e doğrudan istek atsa bile 403 alır). Diğer her şey (personel/kart/cihaz/rapor/firmware) hâlâ tüm giriş yapmış operatörlere açık. Rol ayrımını genişletmek için aynı `permission_classes = [IsAdmin]` deseni ilgili view'lara eklenir.

`is_staff`/`is_superuser` (Django'nun kendi kavramları, `role` alanından bağımsız) yalnızca Django admin panelini (`/admin/`) ilgilendirir — uygulamanın kendi API'si bunları hiç kontrol etmez.

## 6. API Uç Noktaları

Tüm yollar `trailing_slash=False` ile tanımlıdır (sonunda `/` yok). Aksi belirtilmedikçe `Authorization: Bearer <access_token>` gerekir.

### Kimlik doğrulama

| Yöntem | Yol | Açıklama |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{access, refresh}` |
| POST | `/api/auth/refresh` | `{refresh}` → yeni `{access, refresh}` çifti |
| POST | `/api/auth/logout` | `{refresh}` → refresh token'ı blacklist'e ekler (AllowAny) |
| GET | `/api/auth/me` | Giriş yapmış operatörün bilgisi (`role` dahil) |

### Personel / Kart

| Yöntem | Yol | Açıklama |
|---|---|---|
| GET/POST | `/api/employees` | Personel listesi/oluşturma |
| GET/PATCH/DELETE | `/api/employees/{id}` | Detay/güncelleme/soft-delete |
| GET/POST | `/api/cards` | Kart listesi/oluşturma |
| GET/PATCH/DELETE | `/api/cards/{uid}` | Detay/güncelleme/soft-delete |
| POST | `/api/cards/add` | Personel + kartı tek atomik adımda oluşturur (eski "hızlı onboard" akışı) |
| PUT | `/api/cards/{uid}/assign` | Kartı bir personele bağlar/çözer, `is_active` override edebilir |
| POST | `/api/cards/revoke` | `{uid}` → kartı pasifleştirir |

### Cihaz

| Yöntem | Yol | Açıklama |
|---|---|---|
| GET/POST | `/api/devices` | Cihaz listesi/oluşturma |
| GET/PATCH/DELETE | `/api/devices/{id}` | Detay/güncelleme/soft-delete |
| POST | `/api/devices/{id}/command` | `{cmd, payload}` → cihaza MQTT komutu yayınlar (`open`/`sync`/`reboot`/`settime`) |
| POST | `/api/devices/{id}/ota` | `{version}` → cihaza OTA komutu + indirme URL'si yayınlar |

### Firmware

| Yöntem | Yol | Auth | Açıklama |
|---|---|---|---|
| GET | `/api/firmware` | Gerekli | Yüklü firmware sürümleri |
| POST | `/api/firmware/upload` | Gerekli | `.bin` dosyası yükler (multipart) |
| GET | `/api/firmware/{version}/download` | **AllowAny** | ESP32'nin OTA indirmesi için ham binary |

### Olaylar / Rapor / Operatörler

| Yöntem | Yol | Auth | Açıklama |
|---|---|---|---|
| GET | `/api/events` | Gerekli | En yeni 50 geçiş olayı (personel bilgisiyle join'lenmiş) |
| GET | `/api/reports/pdks?start_ts=&end_ts=&employee_id=&format=csv` | Gerekli | Günlük ilk-giriş/son-çıkış ve süre raporu; `format=csv` ile CSV indirir |
| GET/POST | `/api/operators` | Gerekli + **admin** | Operatör listesi/oluşturma — bkz. §5 |

API'nin tamamı DRF'in "browsable API" arayüzü üzerinden kendi kendini belgeler; herhangi bir uç noktayı tarayıcıda (giriş yapmış oturumla) açarak alan listesini ve örnek isteği görebilirsiniz.

## 7. Veri Modeli

Her model (`Employee`, `Card`, `Device`, `Firmware`, `AccessEvent`, `Operator`, `AuditLog`) ortak bir `BaseModel`'den (`core/models.py`) türer:

- `created_at` / `updated_at` — Postgres `db_default` ile üretilir (Django `auto_now_add`/`auto_now` değil), çünkü `collector.py` bu tabloların bir kısmına ham SQL ile ORM'i bypass ederek yazar.
- `deleted_at` / `is_active` — soft-delete; varsayılan `ActiveManager` silinmiş satırları gizler, `all_objects` hepsini gösterir.
- `created_by` / `updated_by` / `deleted_by` — `Operator`'a nullable FK, hangi işlemi kimin yaptığını tutar.

CRUD üzerinden yapılan her değişiklik `AuditedModelViewSet` mixin'i sayesinde otomatik olarak `AuditLog`'a alan-bazlı bir diff (`{"changes": {"alan": {"old": ..., "new": ...}}}`) olarak yazılır — hiçbir view'ın bunu elle çağırması gerekmez. CRUD-dışı özel action'lar (`onboard`, `assign`, `revoke`, `command`, `ota`, `upload`) kendi `log_action()` çağrısını yapar.

**Card:** `uid` (birincil anahtar), `employee` (nullable FK), `floors` (kat bitmask'i için virgüllü liste, 0–31 aralığında), `valid_from`/`valid_to` (Unix zaman damgası), `win_start_m`/`win_end_m` (gün içi izinli pencere, dakika cinsinden 0–1440), `is_active`.

**AccessEvent:** ORM üzerinden değil, doğrudan collector'ın ham SQL'iyle yazılır; `device_id`+`seq` üzerinde `UNIQUE` kısıtı toplayıcının tekilleştirme garantisini veritabanı seviyesinde de sağlar.

## 8. MQTT Toplayıcı Servis (collector.py)

Django'dan tamamen bağımsız, `paho-mqtt` ile broker'a bağlanan sürekli çalışan bir Python scripti. Abone olduğu konular ve karşılık gelen işleyiciler:

| Konu | İşleyici | Yazdığı tablo |
|---|---|---|
| `pdks/{site}/dev/{id}/status` | `handle_status` | `devices` (online/offline) |
| `pdks/{site}/dev/{id}/hb` | `handle_heartbeat` | `devices` (queue_depth, heap_free, uptime vb.) |
| `pdks/{site}/dev/{id}/event` | `handle_event` | `access_events` — ACK gönderir, `uid`'den `employees.id`'yi çözer |
| `pdks/{site}/dev/{id}/cmd/res` | `handle_cmd_res` | `devices` (yalnızca `ota_*` durumları kalıcı yazılır) |

String alanlar (`res`, `dir`, `mode`, `tsrc`) veritabanına yazılmadan önce küçük int kodlara çevrilir (`MAP_RESULT`, `MAP_DIR`, `MAP_MODE`, `MAP_TSRC`); bilinmeyen bir değer güvenli bir varsayılana düşer, servis çökmez. Aynı `(device_id, seq)` ikilisi tekrar geldiğinde veritabanının `UNIQUE` kısıtı `IntegrityError` fırlatır, servis bunu yakalayıp yine de ACK gönderir (cihaz kayıtın işlendiğini bilir) ve devam eder.

## 9. Testler

```bash
# Django testleri (backend/)
cd backend-django/backend
python manage.py test

# Collector testleri (Django test runner'ından bağımsız, sahte cursor/connection ile)
cd backend-django/collector
python -m unittest test_collector.py -v
```

## 10. Bilinen Sınırlamalar

- **MQTT TLS/kimlik doğrulama yok** — `mosquitto.conf` `allow_anonymous true` ile çalışıyor, düz 1883 portu. Bilinçli bir kapsam kararı; ileride TLS (8883) ve kullanıcı adı/parola eklenmesi proje dokümanının FR-17 gereksinimidir.
- **Operatör yönetimi henüz yalnızca ekleme** — `/api/operators` düzenleme/silme desteklemiyor (`OperatorViewSet` yalnızca `GET`/`POST`'a izin veriyor).
- **Retained ACL mesajı** kart sayısı arttıkça büyür; birkaç bin kartı aşan kurulumlarda tek MQTT retained mesajı paket sınırını zorlayabilir, sayfalama/fark yayını gerekebilir.

---

<a name="english-version"></a>
# English Version

# PDKS Backend

A Django REST Framework–based API, a PostgreSQL database, a standalone Python MQTT collector service, and an Eclipse Mosquitto broker. ESP32 door units talk to the collector over MQTT, while the web panel talks to this API over HTTP/JWT.

For hardware/firmware details, see the main `README.md` at the repository root.

## Table of Contents

1. [Services and Architecture](#1-services-and-architecture)
2. [Setup](#2-setup)
3. [Environment Variables](#3-environment-variables)
4. [Project Structure (Django Apps)](#4-project-structure-django-apps)
5. [Authentication and Roles](#5-authentication-and-roles)
6. [API Endpoints](#6-api-endpoints)
7. [Data Model](#7-data-model)
8. [MQTT Collector Service (collector.py)](#8-mqtt-collector-service-collectorpy)
9. [Tests](#9-tests)
10. [Known Limitations](#10-known-limitations)

## 1. Services and Architecture

```
ESP32 door units ──MQTT (QoS1)──> Mosquitto ──> collector.py ──raw SQL──> PostgreSQL <──ORM── Django API <──JWT/HTTP── Vue panel
```

`docker-compose.yml` defines four services:

| Service | Image/Build | Port | Role |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5433→5432 | Database |
| `mosquitto` | `eclipse-mosquitto:2` | 1883, 9001 | MQTT broker (no TLS/authentication, see §10) |
| `backend` | `./backend` | 3000 | Django REST API (this document) |
| `collector` | `./collector` | — | Standalone Python service, listens on MQTT and writes to the database |

The backend and the collector are independent processes: the backend's Django ORM handles normal CRUD operations, while the collector writes the high-frequency event/heartbeat traffic coming from devices directly with raw SQL (without ORM overhead).

## 2. Setup

### With Docker (recommended)

```bash
cd backend-django
cp .env.example .env   # edit the values for your environment, see §3
docker compose up -d --build
```

The backend container automatically runs `python manage.py migrate` on startup. To create the first operator account:

```bash
docker compose exec backend python manage.py createsuperuser
```

### Without Docker (local development)

```bash
cd backend-django/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:3000
```

PostgreSQL and Mosquitto need to be running separately (you can leave `DB_HOST`/`MQTT_HOST` in `.env` as `127.0.0.1`).

To run the collector service separately:

```bash
cd backend-django/collector
pip install -r requirements.txt
python collector.py
```

## 3. Environment Variables

Copied from the `.env.example` file:

| Variable | Default | Description |
|---|---|---|
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_PORT` / `DB_HOST` | `pdks` / `pdks` / `pdks_password` / `5432` / `127.0.0.1` | PostgreSQL connection. Inside Docker Compose, `DB_HOST` is automatically overridden to `postgres`. |
| `MQTT_HOST` / `MQTT_PORT` | `127.0.0.1` / `1883` | Broker address. Inside Docker Compose, `MQTT_HOST` is automatically overridden to `mosquitto`. |
| `DJANGO_SECRET_KEY` | `change-me-in-production` | **Must be changed before going to production.** |
| `DJANGO_DEBUG` | `1` | Should be `0` in production. |
| `DJANGO_ALLOWED_HOSTS` | `*` | Comma-separated list of hosts. |
| `PORT` | `3000` | The port Django listens on. |
| `PANEL_BASE_URL` | — | The **LAN-reachable** address ESP32 devices use to download OTA updates — must NOT be `localhost`, since the ESP32 cannot resolve that. |
| `TZ_OFFSET_MINUTES` | `180` | Used to convert the ACL's time windows from local (TR) time to UTC (`core/acl.py`). |
| `REPORT_TZ` | `Europe/Istanbul` | The timezone used to compute day boundaries in the PDKS report. |

## 4. Project Structure (Django Apps)

| App | Contents |
|---|---|
| `core` | The shared `BaseModel`, audit-log infrastructure (`AuditedModelViewSet`), the `AccessEvent`/`Firmware` models, the event list + PDKS report + firmware upload/download views, ACL binary generation (`acl.py`), MQTT helpers (`mqtt_utils.py`) |
| `accounts` | The `Operator` user model, JWT login/refresh/logout/me views, the `AuditLog` model, admin-only operator management |
| `cards` | The `Employee` and `Card` models, the card onboard/assign/revoke custom actions |
| `devices` | The `Device` model, the command-sending (`command`) and OTA-triggering (`ota`) actions |
| `config` | Django settings and URL routing |

## 5. Authentication and Roles

**JWT** (`djangorestframework-simplejwt`): access tokens live 15 minutes, refresh tokens live 7 days, with rotation and blacklist-on-refresh enabled (a stolen refresh token can never be reused indefinitely). Tokens are stored in `localStorage` (the panel is only used from a trusted internal network, so the httpOnly-cookie/CSRF complexity wasn't taken on).

`DEFAULT_PERMISSION_CLASSES` is `IsAuthenticated` project-wide — the one exception is `FirmwareViewSet.download` (the ESP32's OTA download, which can't produce a JWT, is deliberately `AllowAny`).

**Roles:** `Operator.role`, either `admin` or `operator` (default `operator`). As of today, there is exactly one difference between them: **creating operator accounts** (the `/operators` page, visible in the panel only to admins; enforced on the backend by `IsAdmin` in `accounts/permissions.py` — a non-admin gets a 403 even if they hit the endpoint directly). Everything else (employees/cards/devices/reports/firmware) is still open to any logged-in operator. Extending the role split further means adding the same `permission_classes = [IsAdmin]` pattern to the relevant views.

`is_staff`/`is_superuser` (Django's own concepts, independent of the `role` field) only matter for the Django admin panel (`/admin/`) — the app's own API never checks them.

## 6. API Endpoints

All paths are defined with `trailing_slash=False` (no trailing `/`). Unless otherwise noted, `Authorization: Bearer <access_token>` is required.

### Authentication

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{access, refresh}` |
| POST | `/api/auth/refresh` | `{refresh}` → a new `{access, refresh}` pair |
| POST | `/api/auth/logout` | `{refresh}` → blacklists the refresh token (AllowAny) |
| GET | `/api/auth/me` | Info about the logged-in operator (including `role`) |

### Employees / Cards

| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/employees` | List/create employees |
| GET/PATCH/DELETE | `/api/employees/{id}` | Detail/update/soft-delete |
| GET/POST | `/api/cards` | List/create cards |
| GET/PATCH/DELETE | `/api/cards/{uid}` | Detail/update/soft-delete |
| POST | `/api/cards/add` | Creates an employee + card in a single atomic step (the old "quick onboard" flow) |
| PUT | `/api/cards/{uid}/assign` | Assigns/unassigns a card to an employee, can override `is_active` |
| POST | `/api/cards/revoke` | `{uid}` → deactivates a card |

### Devices

| Method | Path | Description |
|---|---|---|
| GET/POST | `/api/devices` | List/create devices |
| GET/PATCH/DELETE | `/api/devices/{id}` | Detail/update/soft-delete |
| POST | `/api/devices/{id}/command` | `{cmd, payload}` → publishes an MQTT command to the device (`open`/`sync`/`reboot`/`settime`) |
| POST | `/api/devices/{id}/ota` | `{version}` → publishes an OTA command + download URL to the device |

### Firmware

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/firmware` | Required | Registered firmware versions |
| POST | `/api/firmware/upload` | Required | Uploads a `.bin` file (multipart) |
| GET | `/api/firmware/{version}/download` | **AllowAny** | Raw binary for the ESP32's OTA download |

### Events / Report / Operators

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/events` | Required | The 50 most recent access events (joined with employee info) |
| GET | `/api/reports/pdks?start_ts=&end_ts=&employee_id=&format=csv` | Required | Daily first-in/last-out and duration report; `format=csv` downloads as CSV |
| GET/POST | `/api/operators` | Required + **admin** | List/create operators — see §5 |

The entire API self-documents through DRF's "browsable API" interface — you can open any endpoint in a browser (with a logged-in session) to see its field list and a sample request.

## 7. Data Model

Every model (`Employee`, `Card`, `Device`, `Firmware`, `AccessEvent`, `Operator`, `AuditLog`) derives from a shared `BaseModel` (`core/models.py`):

- `created_at` / `updated_at` — generated via Postgres `db_default` (not Django's `auto_now_add`/`auto_now`), because `collector.py` writes to some of these tables with raw SQL, bypassing the ORM entirely.
- `deleted_at` / `is_active` — soft delete; the default `ActiveManager` hides deleted rows, `all_objects` shows all of them.
- `created_by` / `updated_by` / `deleted_by` — nullable FKs to `Operator`, recording who performed which action.

Every change made through CRUD is automatically written to `AuditLog` as a field-level diff (`{"changes": {"field": {"old": ..., "new": ...}}}`) via the `AuditedModelViewSet` mixin — no view needs to call this by hand. Non-CRUD custom actions (`onboard`, `assign`, `revoke`, `command`, `ota`, `upload`) make their own `log_action()` call.

**Card:** `uid` (primary key), `employee` (nullable FK), `floors` (comma-separated list for the floor bitmask, range 0–31), `valid_from`/`valid_to` (Unix timestamps), `win_start_m`/`win_end_m` (allowed time-of-day window, in minutes, 0–1440), `is_active`.

**AccessEvent:** written directly by the collector's raw SQL, not through the ORM; a `UNIQUE` constraint on `device_id`+`seq` also enforces the collector's deduplication guarantee at the database level.

## 8. MQTT Collector Service (collector.py)

A long-running Python script, fully independent of Django, that connects to the broker with `paho-mqtt`. The topics it subscribes to and their handlers:

| Topic | Handler | Table written |
|---|---|---|
| `pdks/{site}/dev/{id}/status` | `handle_status` | `devices` (online/offline) |
| `pdks/{site}/dev/{id}/hb` | `handle_heartbeat` | `devices` (queue_depth, heap_free, uptime, etc.) |
| `pdks/{site}/dev/{id}/event` | `handle_event` | `access_events` — sends an ACK, resolves `employees.id` from the `uid` |
| `pdks/{site}/dev/{id}/cmd/res` | `handle_cmd_res` | `devices` (only `ota_*` statuses are persisted) |

String fields (`res`, `dir`, `mode`, `tsrc`) are converted to small integer codes before being written to the database (`MAP_RESULT`, `MAP_DIR`, `MAP_MODE`, `MAP_TSRC`); an unknown value falls back to a safe default rather than crashing the service. When the same `(device_id, seq)` pair arrives again, the database's `UNIQUE` constraint raises an `IntegrityError`, which the service catches, still sends an ACK (so the device knows the record was processed), and continues.

## 9. Tests

```bash
# Django tests (backend/)
cd backend-django/backend
python manage.py test

# Collector tests (independent of the Django test runner, using fake cursor/connection objects)
cd backend-django/collector
python -m unittest test_collector.py -v
```

## 10. Known Limitations

- **No MQTT TLS/authentication** — `mosquitto.conf` runs with `allow_anonymous true`, on plain port 1883. A deliberate scope decision; adding TLS (8883) and username/password later is required by FR-17 of the project specification.
- **Operator management currently only supports adding** — `/api/operators` doesn't support edit/delete (`OperatorViewSet` only allows `GET`/`POST`).
- **The retained ACL message** grows with the number of cards; installations with more than a few thousand cards could hit the MQTT retained-message packet size limit, which may eventually require pagination/delta publishing.
