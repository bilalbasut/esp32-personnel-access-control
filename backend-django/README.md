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
