# ESP32-Based Ethernet PDKS and Floor-Based Access Control System

*This document is written primarily in Turkish, the working language of this internship project. An English translation is included at the end of this file — jump to [English Version](#english-version).*

---

# ESP32 Tabanlı Ethernet PDKS ve Katlı Geçiş Kontrol Sistemi

Çok katlı(veya güvenlik seviyeli) bir bina için RFID kartlı geçiş kontrol ve personel devam kontrol sistemi (PDKS). Her kat girişine bir ESP32 tabanlı "kapı ünitesi" yerleştirilir; kart okutulduğunda erişim kararı **her zaman cihazın kendi üzerinde**, yerel yetki listesine (ACL) bakılarak verilir. Ağ/sunucu/broker erişilemez olsa bile kapılar kilitlenmez, geçişler yerel yetki listesine göre sürmeye devam eder ve üretilen tüm kayıtlar cihaz üzerinde kalıcı olarak saklanıp bağlantı geri geldiğinde tek bir kayıt bile kaybolmadan/tekrarlanmadan sunucuya aktarılır.

Bu doküman, sistemi sıfırdan kurmak için gereken donanım ve firmware detaylarını içerir. Backend (Django API), MQTT toplayıcı servis ve web paneli ile ilgili detaylar için `backend-django/README.md` dosyasına bakın.

Projenin orijinal görev tanımı `ESP32_PDKS_Staj_Projesi.pdf` dosyasındadır. Bu README'de o dokümandan sapılan üç nokta açıkça belirtilmiştir: gerçek zaman saati modülü (DS3231 yerine PCF8563), kapı konum (manyetik) sensörü (kullanılmadı) ve MQTT şifrelemesi (kapsam dışı bırakıldı).

## İçindekiler

1. [Sistem Mimarisi](#1-sistem-mimarisi)
2. [Donanım Kurulumu](#2-donanım-kurulumu)
3. [Firmware](#3-firmware)
4. [Backend Özeti (Yüzeysel)](#4-backend-özeti-yüzeysel)
5. [Bilinen Sınırlamalar / Kapsam Dışı Bırakılanlar](#5-bilinen-sınırlamalar--kapsam-dışı-bırakılanlar)
6. [Referanslar](#6-referanslar)

## 1. Sistem Mimarisi

```
RFID kart → MFRC522 → ESP32 (yerel ACL + karar) → röle/turnike
                              │
                              ├─ olay her zaman önce flash'a yazılır (RAM'de beklemez)
                              └─ MQTT (QoS1) ile sunucuya yayınlanır → toplayıcı servis → PostgreSQL → web paneli
```

Tasarım ilkeleri (proje dokümanı §2.1 ile birebir aynı, değiştirilmedi):

- **Karar yerelde verilir.** Kart okunduğunda sunucuya soru sorulmaz; cihazdaki ACL kopyasına bakılır.
- **Kayıt asla RAM'de beklemez.** Olay, röle çekilmeden önce kalıcı belleğe (flash) yazılır.
- **Silme yalnızca onaydan sonra.** Kuyruk göstergesi, sunucudan gelen ACK mesajıyla ilerletilir.
- **Tekrar kabul edilir, kopya kabul edilmez.** QoS1 aynı mesajı iki kez teslim edebilir; tekilleştirme sunucu tarafında (cihaz kimliği + sıra numarası) yapılır.
- **Hiçbir yerde `delay()` yoktur.** Tüm zamanlama `millis()`/FreeRTOS tabanlıdır.

## 2. Donanım Kurulumu

### 2.1 Malzeme Listesi (Kapı Ünitesi Başına)

| # | Bileşen | Kullanılan | Görev |
|---|---------|-----------|-------|
| 1 | Mikrodenetleyici | ESP32-WROOM-32 DevKit v1 (30/38 pin) | Ana işlemci |
| 2 | Ethernet modülü | W5500 (SPI) | Kablolu ağ bağlantısı |
| 3 | RFID okuyucu | MFRC522 (13.56 MHz) | Kart/etiket okuma |
| 4 | RFID kart/etiket | Mifare Classic 1K | Test kullanıcıları |
| 5 | Gerçek zaman saati | **PCF8563** (I2C) | Çevrimdışıyken doğru zaman damgası — bkz. not aşağıda |
| 6 | Röle | Çıplak **SRD-05VDC-SL-C** (5 V bobin, hazır sürücü modülü değil) | Turnike/kapı kuru kontak sürme |
| 7 | Röle sürücü | **2N2222A** NPN transistör + 330 Ω baz direnci | Röle bobinini 3.3 V mantık sinyaliyle sürmek — bkz. §2.5 |
| 8 | Gösterge | Yeşil + kırmızı LED, aktif buzzer | Kullanıcı geri bildirimi |
| 9 | Giriş | Çıkış butonu | Manuel açma |
| 10 | Güç | 5 V / 2 A adaptör + **LM2596 buck modül** (3.3 V'a ayarlı) | Ayrı 3.3 V hattı — bkz. §2.4 |
| 11 | Sarf | Breadboard/delikli pertinaks, jumper, dirençler | Montaj |

**Not (DS3231 → PCF8563):** Proje dokümanı DS3231 öneriyordu; temin sorunu nedeniyle PCF8563 kullanıldı. Firmware'de `adafruit/RTClib` kütüphanesi kullanıldığı için ikisi de aynı arayüzle desteklenir, kod tarafında değişiklik gerekmedi (`hal/rtc_service.cpp`, `RTC_PCF8563` sınıfı).

**Kullanılmayanlar:** Kapı konum (manyetik) sensörü ve opsiyonel OLED ekran bu teslimde yok — ikisi de proje dokümanında opsiyonel/gerekli değildi.

### 2.2 Pin Haritası

Aşağıdaki tablo firmware'in gerçek kaynağından (`include/config.h`) alınmıştır; proje dokümanının referans pin haritasıyla neredeyse birebir aynıdır.

| Modül / Sinyal | GPIO | Arayüz | Not |
|---|---|---|---|
| W5500 — SCK / MISO / MOSI | 18 / 19 / 23 | VSPI | Donanım SPI |
| W5500 — CS | 5 | VSPI | Boot'ta HIGH kalmalı (varsayılan pull-up uygun) |
| W5500 — RST | 4 | GPIO | Açılışta 1 ms LOW darbe (`network_manager.cpp`) |
| MFRC522 — SCK / MISO / MOSI | 14 / 27 / 13 | HSPI | **W5500'den ayrı SPI hattı** — aynı hat kullanılırsa CS çakışması/rastgele donma olur (bkz. §5) |
| MFRC522 — SS (CS) | 15 | HSPI | Boot'ta HIGH, CS boşta HIGH olduğundan uygun |
| MFRC522 — RST | — | — | Yazılımda sürülmüyor; modülün RST ucu 3.3 V'a sabit bağlı (donanımsal olarak hep aktif) |
| PCF8563 — SDA / SCL | 21 / 22 | I2C | Adres 0x51 |
| Röle tetikleme | 32 | GPIO çıkış | 2N2222A transistör üzerinden — doğrudan bobini sürmez, bkz. §2.5 |
| Buzzer | 33 | GPIO çıkış | Aktif buzzer, doğrudan sürülür |
| Yeşil LED | 25 | GPIO çıkış | Seri 220–330 Ω direnç |
| Kırmızı LED | 17 | GPIO çıkış | Seri 220–330 Ω direnç |
| Çıkış butonu | 35 | GPIO **giriş** | Yalnızca-giriş pin, dahili pull-up yok — **harici 10 kΩ pull-up zorunlu**, bkz. §2.3 |

**Pin uyarıları (ESP32-WROOM-32 donanım kısıtları):** GPIO6–11 dahili flash'a ayrılmıştır, kullanılamaz. GPIO34/35/36/39 yalnızca giriştir ve dahili pull-up/pull-down içermez. GPIO12 (MTDI) bir strapping pinidir; boot anında HIGH çekilirse kart açılmaz — bu yüzden yukarıdaki haritada kullanılmamıştır. Pin ataması gerekirse değiştirilebilir, ancak bu kısıtlar korunmalıdır.

### 2.3 Pull-up Direnci Nedir? (Çıkış Butonu Örneği)

Bir dijital giriş pini hiçbir yere bağlı değilken ("floating") gerilimi belirsizdir; elektriksel gürültü pini rastgele HIGH/LOW arasında sıçratabilir, buton basılı olmasa bile yanlış tetiklemeler oluşabilir. **Pull-up direnci**, pini bir direnç üzerinden besleme gerilimine (3.3 V) bağlayarak pinin varsayılan (buton basılı değilken) durumunu kararlı biçimde HIGH'da tutar; buton basıldığında pin GND'ye çekilir ve net bir LOW okunur.

Devre: `3.3V → 10 kΩ direnç → GPIO35 → buton → GND`.

ESP32'nin GPIO35'i (34/36/39 ile birlikte) yalnızca-giriş bir pindir ve içinde donanımsal pull-up/pull-down devresi **yoktur** — yani `pinMode(pin, INPUT_PULLUP)` gibi yazılımsal bir çözüm burada işe yaramaz, direncin fiziksel olarak devrede olması zorunludur. Firmware tarafında da 50 ms'lik bir debounce uygulanır (`EXIT_DEBOUNCE_MS`, `hal/io_controller.cpp`) — mekanik buton kontağının sıçraması (bounce) tek basışı birden çok basış gibi göstermesin diye.

### 2.4 Güç Mimarisi

Sistemde iki ayrı gerilim hattı var: **5 V** (röle bobini + ana giriş) ve **3.3 V** (ESP32, W5500, MFRC522, PCF8563, LED'ler — tüm mantık/sinyal devresi).

**Neden ESP32'nin kendi 3.3 V'u kullanılmadı:** ESP32 DevKit kartının üzerindeki yerleşik 3.3 V regülatörü, Wi-Fi/Ethernet gibi ani akım tepe (peak) anlarında yetersiz kalabiliyor; W5500 modülünün kendisi de anlık ~150–200 mA çekebiliyor. Bu ek yükü kartın kendi küçük regülatörüne bindirmek rastgele yeniden başlama ve brownout hatalarına yol açabiliyordu (proje dokümanı §9'da da bu risk ayrıca belirtilmiş). Bu yüzden ESP32'nin kendi 3.3 V pinini/regülatörünü kullanmak yerine, tüm 3.3 V mantık hattı (ESP32 dahil) ayrı ve yeterli akım kapasitesine sahip harici bir regülatörden besleniyor.

**Kullanılan regülatör:** LM2596 buck (düşürücü) modül, çıkışı 3.3 V'a ayarlanmış, soğutmasız halde 2 A'e kadar besleyebiliyor (proje dokümanının önerdiği iki seçenekten biri — AMS1117 doğrusal regülatör yerine buck alternatifi tercih edildi).

**Güç akışı:**
```
5V/2A adaptör ──┬── LM2596 (giriş) ── LM2596 (çıkış, 3.3V) ── ESP32(3.3V pini) + W5500 + MFRC522 + PCF8563 + LED'ler
                └── Röle bobini (+) doğrudan 5V
```
Tek bir ana güç kaynağı var; ondan hem doğrudan 5 V (röle bobini) hem de regüle edilmiş 3.3 V (mantık devresi) türetiliyor.

**Kondansatörler:** Regülatör giriş/çıkış uçlarında **100 nF (seramik) + 470 µF (elektrolitik)** paralel kondansatör çifti kullanıldı — 100 nF yüksek frekanslı anahtarlama gürültüsünü söndürür, 470 µF ani akım taleplerinde kısa süreli enerji deposu görevi görüp brownout'u önler. Bu çift hem LM2596'nın 3.3 V çıkışında (ESP32/W5500/MFRC522 tarafında) hem de röle bobininin bağlı olduğu 5 V hattında bulunuyor.

**Ortak toprak (GND):** 5 V ve 3.3 V devrelerinin GND hatları **tek noktadan** birleştirildi (star ground) — iki ayrı GND dönüş yolu oluşup aralarında gürültü/gerilim farkı yaratmaması için.

### 2.5 Röle Sürücü Devresi (5V/3.3V Sınırındaki Tek Ortak Eleman)

5 V (röle bobini) ve 3.3 V (mantık) devrelerinin birbirine dokunduğu **tek nokta röle**. Kullanılan röle hazır bir "3.3 V tetikli sürücü modülü" değil, çıplak **SRD-05VDC-SL-C** bobin/kontak seti — yani onu doğrudan bir GPIO'ya bağlamak hem akım yetersizliği (ESP32 GPIO başına güvenle çekebileceği akım ~12 mA civarındayken röle bobini bunun kat kat üzerinde akım çeker) hem de 5 V'un GPIO'ya geri yansıma riski taşırdı. Bu yüzden aradaki anahtarlamayı bir transistör üstleniyor.

**Devre:**
```
GPIO32 ── 330Ω (baz direnci) ── 2N2222A (Base)
                                 2N2222A (Emitter) ── ortak GND
                                 2N2222A (Collector) ── Röle bobini (−)
                                                          Röle bobini (+) ── 5V
```

**Çalışma mantığı:** GPIO32 HIGH (3.3 V) olduğunda, 330 Ω üzerinden akan küçük bir baz akımı 2N2222A'yı doyuma (saturation) sokar; kollektör-emiter arası neredeyse kısa devre gibi davranır ve bobin akımı 5 V hattından GND'ye akar — transistör burada **düşük-taraf (low-side) anahtar** olarak çalışır. GPIO LOW olduğunda transistör kesimde (cutoff) kalır, bobinden akım geçmez, röle bırakır.

Bu sayede GPIO32 hiçbir zaman 5 V görmez ve hiçbir zaman bobin akımını doğrudan sürmez — sadece birkaç mA'lık küçük bir baz akımını anahtarlar; tüm 5 V / yüksek akım tarafı transistör ve ayrı 5 V hattı üzerinde kalır.

> **Bilinen eksik / önerilen iyileştirme:** Bobin üzerinde şu an bir flyback (geri tepme) diodu **yok**. Röle her bırakıldığında bobinin endüktif geri-EMF'i, transistörün kollektör ucunda kısa süreli yüksek gerilim darbesi oluşturabilir; bu hem 2N2222A'yı zamanla yıpratabilir hem de aynı 5 V hattındaki gürültüyü artırabilir. Standart ve ucuz çözüm: bobinin iki ucuna ters kutuplu bir **1N4007** (veya benzeri) diyot eklemek (katot 5 V ucuna, anot kollektör ucuna). Devreye eklenmesi önerilir — şu anki teslim edilen halde bu diyot yok.

**Turnike/kilit bağlantısı:** Bu teslim edilen ünitede fiziksel bir turnike veya elektrikli kilit **bağlı değil** — röle kontakları (NO/COM) test/demo amaçlı boşta bırakıldı. Gerçek kuruluma geçildiğinde turnike/kilit kendi ayrı güç kaynağıyla röle kontaklarına bağlanacak şekilde tasarlandı; röle bobini ve turnike beslemesi birbirinden bağımsız tutulmalı, GND yalnızca tek noktadan birleştirilmelidir (proje dokümanı §3.3'te de aynı gereksinim belirtiliyor).

### 2.6 LED / Buzzer Kablolama

- **Yeşil LED (GPIO25) ve kırmızı LED (GPIO17):** her biri için GPIO çıkışı ile LED anotu arasına seri **220–330 Ω** direnç (proje dokümanının belirttiği aralık; 330 Ω kullanıldı) — LED akımını hem GPIO'nun hem LED'in güvenli sınırında (yaklaşık 10–15 mA) tutmak için.
- **Buzzer (GPIO33):** aktif (kendi osilatörlü) buzzer, doğrudan GPIO'dan sürülüyor — PWM sinyaline gerek yok, kısa bip = kabul, uzun bip = ret.

### 2.7 Güç Bağlantı Özeti

| Modül | Beslendiği hat |
|---|---|
| ESP32, W5500, MFRC522, PCF8563, LED'ler | 3.3 V (LM2596 çıkışı) |
| Röle bobini | 5 V (ana adaptör, doğrudan) |
| Röle tetikleme sinyali (GPIO32) | 3.3 V mantık — transistör ile 5 V tarafından izole (bkz. §2.5) |
| Turnike/kilit (gerçek kurulumda) | Kendi ayrı besleme hattı, röle kontakları üzerinden anahtarlanır |

## 3. Firmware

### 3.1 Geliştirme Ortamı

- VS Code + PlatformIO, Arduino framework
- Board: `esp32doit-devkit-v1`, platform `espressif32@6.10.0`
- Dosya sistemi: LittleFS
- Özel partition tablosu (`partitions_two_ota.csv`): iki OTA slotu (`ota_0` / `ota_1`, ~1.75 MB'ar) + ayrı bir veri bölümü (kalıcı olay kuyruğu ve ACL dosyaları burada tutulur)

### 3.2 Kütüphaneler (`platformio.ini`)

| Kütüphane | Görev |
|---|---|
| `OSSLibraries/Arduino_MFRC522v2` | RFID okuma (resmi v2 kütüphanesi, GitHub'dan klonlanır) |
| `arduino-libraries/Ethernet` | W5500 TCP/IP yığını |
| `256dpi/MQTT` | MQTT istemcisi (QoS1, LWT, retained mesaj desteği) |
| `bblanchon/ArduinoJson` | JSON kodlama/çözme |
| `adafruit/RTClib` | RTC (hem DS3231 hem PCF8563 destekler) |
| `arduino-libraries/NTPClient` | Ağ zaman senkronizasyonu |

### 3.3 Modül Yapısı

| Dosya | Görev |
|---|---|
| `src/main.cpp` | `setup()`/`loop()`, watchdog, ağ görevinin (task) ayrı çekirdekte başlatılması |
| `src/hal/io_controller.*` | Röle/LED/buzzer/çıkış butonu durum makinesi — `delay()` yok, `millis()` tabanlı |
| `src/hal/rfid_reader.*` | MFRC522 okuma, debounce (5 sn), geçiş olayı akışını tetikleme |
| `src/hal/rtc_service.*` | PCF8563 okuma, NTP/RTC/geçersiz zaman kaynağı yönetimi ve "dead reckoning" yedek mekanizması |
| `src/domain/acl_engine.*` | Yerel yetki listesi (LittleFS'te ikili format), ikili arama, erişim kararı |
| `src/storage/event_queue.*` | Kalıcı, yalnızca-sona-ekleyen (append-only) olay kuyruğu, CRC16 doğrulama, checkpoint |
| `src/network/network_manager.*` | W5500 + MQTT istemcisi, QoS1 store-and-forward, komut kuyruğu |
| `src/network/ota_guard.*`, `src/network/ota_updater.*` | OTA güncelleme ve kendiliğinden geri alma (rollback) koruması |

### 3.4 Derleme ve Yükleme

```
pio run -t upload
```

(veya VS Code'daki PlatformIO arayüzünden "Upload"). Seri port otomatik algılanır; seri monitör 115200 baud.

`include/config.h` içinde her kapı için `DEVICE_ID`, `FLOOR_NUMBER`, `DEVICE_DIR` ve ağ ayarları (statik IP, MQTT broker adresi) **derleme zamanında** sabitlenir — **her kapı kendi binary'siyle flaşlanır, aynı `.bin` iki farklı kapıya yüklenemez.** Yeni bir kapı eklerken bu sabitleri değiştirip yeniden derlemek gerekir.

İlk yüklemeden sonra yerel ACL ve kalıcı kuyruk boş başlar; ACL, backend'den gelen retained MQTT mesajıyla otomatik senkronize olur.

## 4. Backend Özeti (Yüzeysel)

- **Django 5 + Django REST Framework**, PostgreSQL veritabanı, JWT (access/refresh) ile kimlik doğrulama, admin/operator rol ayrımı
- **Python MQTT toplayıcı servisi** (`collector.py`) — ham SQL ile `access_events`/`devices` tablolarına yazar
- **Eclipse Mosquitto** broker, 1883 portu — TLS/kimlik doğrulama yok (bkz. §5)
- **Vue 3** web paneli — personel/kart/cihaz yönetimi, PDKS raporu (CSV dışa aktarım), denetim günlüğü, operatör hesap yönetimi
- Tüm servisler `docker-compose.yml` ile tek komutla ayağa kalkar

Detaylı kurulum, API uç noktaları, veri modeli ve test talimatları için **`backend-django/README.md`** dosyasına bakın.

## 5. Bilinen Sınırlamalar / Kapsam Dışı Bırakılanlar

| Konu | Durum |
|---|---|
| MQTT TLS / kimlik doğrulama | Kapsam dışı bırakıldı (bilinçli karar) — broker `allow_anonymous true` ile çalışıyor, düz 1883 |
| Kapı konum (manyetik) sensörü | Kullanılmadı — proje dokümanında opsiyoneldi |
| Turnike / elektrikli kilit | Bu teslim edilen ünitede fiziksel olarak bağlı değil — röle kontakları hazır (bkz. §2.5) |
| Röle bobininde flyback diyodu | Yok — 1N4007 eklenmesi önerilir (bkz. §2.5) |
| Gerçek zaman saati | DS3231 yerine PCF8563 kullanıldı (temin sorunu) |
| Retained ACL mesajı büyüklüğü | Kart sayısı birkaç bini aşarsa tek MQTT retained mesajı paket sınırını zorlayabilir — sayfalama/fark (delta) yayını ileride gerekebilir, şu anki ayrılan 16KB'lık RAM ile 800 karta kadar bu versiyon bilerek bırakıldı, bence daha iyi|
| RC522/W5500 aynı SPI hattında | Bilerek ayrı SPI hattına (VSPI/HSPI) alındı, aynı hatta bırakılırsa CS çakışması/rastgele donma riski var |

## 6. Referanslar

- Orijinal görev tanımı: `ESP32_PDKS_Staj_Projesi.pdf`
- Backend/API detayları: `backend-django/README.md`
- ESP32 Teknik Referans Kılavuzu ve ESP32-WROOM-32 veri sayfası (Espressif)

---

<a name="english-version"></a>
# English Version

# ESP32-Based Ethernet PDKS and Floor-Based Access Control System

Multi-floor (or security-tiered) building RFID card-based access control and personnel attendance tracking system (PDKS – Personel Devam Kontrol Sistemi). An ESP32-based "door unit" is installed at each floor entrance; when a card is scanned, the access decision is **always made on the device itself**, based on its local authorization list (ACL). Even if the network/server/broker becomes unreachable, doors are not locked out — access continues to be granted based on the local ACL, and every generated record is stored persistently on the device and transferred to the server once connectivity returns, without a single record being lost or duplicated.

This document contains the hardware and firmware details needed to set up the system from scratch. For details on the backend (Django API), the MQTT collector service, and the web panel, see `backend-django/README.md`.

The project's original task specification is in `ESP32_PDKS_Staj_Projesi.pdf`. This README explicitly calls out three points where the implementation deviates from that document: the real-time clock module (PCF8563 instead of DS3231), the door position (magnetic) sensor (not used), and MQTT encryption (left out of scope).

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Hardware Setup](#2-hardware-setup)
3. [Firmware](#3-firmware)
4. [Backend Summary (High-Level)](#4-backend-summary-high-level)
5. [Known Limitations / Out-of-Scope Items](#5-known-limitations--out-of-scope-items)
6. [References](#6-references)

## 1. System Architecture

```
RFID card → MFRC522 → ESP32 (local ACL + decision) → relay/turnstile
                              │
                              ├─ the event is always written to flash first (never waits in RAM)
                              └─ published to the server over MQTT (QoS1) → collector service → PostgreSQL → web panel
```

Design principles (identical to §2.1 of the project specification, unchanged):

- **The decision is made locally.** When a card is read, no question is sent to the server; the device's own copy of the ACL is checked.
- **A record never waits in RAM.** The event is written to persistent memory (flash) before the relay is energized.
- **Deletion only happens after acknowledgment.** The queue pointer only advances once an ACK is received from the server.
- **Retransmission is accepted, duplication is not.** QoS1 can deliver the same message twice; deduplication is done server-side (by device ID + sequence number).
- **`delay()` is never used anywhere.** All timing is based on `millis()`/FreeRTOS.

## 2. Hardware Setup

### 2.1 Bill of Materials (Per Door Unit)

| # | Component | Used | Role |
|---|---------|-----------|-------|
| 1 | Microcontroller | ESP32-WROOM-32 DevKit v1 (30/38 pin) | Main processor |
| 2 | Ethernet module | W5500 (SPI) | Wired network connection |
| 3 | RFID reader | MFRC522 (13.56 MHz) | Card/tag reading |
| 4 | RFID card/tag | Mifare Classic 1K | Test users |
| 5 | Real-time clock | **PCF8563** (I2C) | Accurate timestamps while offline — see note below |
| 6 | Relay | Bare **SRD-05VDC-SL-C** (5V coil, not a pre-built driver module) | Driving the turnstile/door's dry contact |
| 7 | Relay driver | **2N2222A** NPN transistor + 330Ω base resistor | Driving the relay coil from a 3.3V logic signal — see §2.5 |
| 8 | Indicators | Green + red LED, active buzzer | User feedback |
| 9 | Input | Exit button | Manual unlock |
| 10 | Power | 5V/2A adapter + **LM2596 buck module** (set to 3.3V) | Separate 3.3V rail — see §2.4 |
| 11 | Consumables | Breadboard/perfboard, jumper wires, resistors | Assembly |

**Note (DS3231 → PCF8563):** The project specification recommended the DS3231; the PCF8563 was used instead due to a sourcing issue. Since the firmware uses the `adafruit/RTClib` library, both chips are supported through the same interface, so no code changes were needed (`hal/rtc_service.cpp`, `RTC_PCF8563` class).

**Not used:** The door position (magnetic) sensor and the optional OLED display are not present in this delivery — both were optional/not required in the project specification.

### 2.2 Pin Map

The table below is taken directly from the firmware's actual source (`include/config.h`); it is nearly identical to the reference pin map in the project specification.

| Module / Signal | GPIO | Interface | Note |
|---|---|---|---|
| W5500 — SCK / MISO / MOSI | 18 / 19 / 23 | VSPI | Hardware SPI |
| W5500 — CS | 5 | VSPI | Must stay HIGH at boot (default pull-up is fine) |
| W5500 — RST | 4 | GPIO | 1ms LOW pulse at startup (`network_manager.cpp`) |
| MFRC522 — SCK / MISO / MOSI | 14 / 27 / 13 | HSPI | **Separate SPI bus from the W5500** — sharing the same bus causes CS conflicts / random hangs (see §5) |
| MFRC522 — SS (CS) | 15 | HSPI | HIGH at boot, which is fine since idle CS is HIGH |
| MFRC522 — RST | — | — | Not driven in software; the module's RST pin is hard-wired to 3.3V (always active in hardware) |
| PCF8563 — SDA / SCL | 21 / 22 | I2C | Address 0x51 |
| Relay trigger | 32 | GPIO output | Through the 2N2222A transistor — does not drive the coil directly, see §2.5 |
| Buzzer | 33 | GPIO output | Active buzzer, driven directly |
| Green LED | 25 | GPIO output | 220–330Ω series resistor |
| Red LED | 17 | GPIO output | 220–330Ω series resistor |
| Exit button | 35 | GPIO **input** | Input-only pin, no internal pull-up — **an external 10kΩ pull-up is mandatory**, see §2.3 |

**Pin warnings (ESP32-WROOM-32 hardware constraints):** GPIO6–11 are reserved for the internal flash and cannot be used. GPIO34/35/36/39 are input-only and have no internal pull-up/pull-down. GPIO12 (MTDI) is a strapping pin; if pulled HIGH at boot, the board fails to start — which is why it is not used in the map above. Pin assignments can be changed if needed, but these constraints must be respected.

### 2.3 What Is a Pull-Up Resistor? (Exit Button Example)

When a digital input pin is left unconnected ("floating"), its voltage is undefined; electrical noise can randomly flip the pin between HIGH and LOW, causing false triggers even when the button isn't pressed. A **pull-up resistor** connects the pin to the supply voltage (3.3V) through a resistor, holding the pin's default (button-not-pressed) state reliably at HIGH; when the button is pressed, the pin is pulled to GND and reads a clean LOW.

Circuit: `3.3V → 10kΩ resistor → GPIO35 → button → GND`.

The ESP32's GPIO35 (along with 34/36/39) is an input-only pin and has **no** internal pull-up/pull-down circuitry — meaning a software-only solution like `pinMode(pin, INPUT_PULLUP)` does not work here; the resistor must be physically present in the circuit. The firmware also applies a 50ms debounce (`EXIT_DEBOUNCE_MS`, `hal/io_controller.cpp`) so that mechanical contact bounce doesn't register a single press as multiple presses.

### 2.4 Power Architecture

The system has two separate voltage rails: **5V** (relay coil + main input) and **3.3V** (ESP32, W5500, MFRC522, PCF8563, LEDs — the entire logic/signal circuitry).

**Why the ESP32's own 3.3V is not used:** The ESP32 DevKit board's onboard 3.3V regulator can struggle during sudden current spikes such as Wi-Fi/Ethernet activity; the W5500 module itself can momentarily draw ~150–200mA. Putting this extra load on the board's small onboard regulator was causing random reboots and brownout errors (this risk is also specifically called out in §9 of the project specification). For this reason, instead of using the ESP32's own 3.3V pin/regulator, the entire 3.3V logic rail (including the ESP32 itself) is powered from a separate external regulator with sufficient current capacity.

**Regulator used:** An LM2596 buck (step-down) module, output set to 3.3V, capable of supplying up to 2A without a heatsink (one of the two options suggested in the project specification — the buck alternative was chosen over the AMS1117 linear regulator).

**Power flow:**
```
5V/2A adapter ──┬── LM2596 (input) ── LM2596 (output, 3.3V) ── ESP32 (3.3V pin) + W5500 + MFRC522 + PCF8563 + LEDs
                └── Relay coil (+) directly from 5V
```
There is a single main power source, from which both direct 5V (relay coil) and regulated 3.3V (logic circuit) are derived.

**Capacitors:** A **100nF (ceramic) + 470µF (electrolytic)** parallel capacitor pair is used at the regulator's input/output — the 100nF suppresses high-frequency switching noise, and the 470µF acts as a short-term energy reservoir during sudden current demand, preventing brownouts. This pair is present both on the LM2596's 3.3V output (ESP32/W5500/MFRC522 side) and on the 5V rail the relay coil is connected to.

**Common ground (GND):** The GND lines of the 5V and 3.3V circuits are joined at a **single point** (star ground) — so that two separate GND return paths don't form and create noise/voltage differences between them.

### 2.5 Relay Driver Circuit (the Single Common Element Between the 5V/3.3V Boundary)

The relay is the **single point** where the 5V (relay coil) and 3.3V (logic) circuits touch. The relay used is not a ready-made "3.3V-triggered driver module" but a bare **SRD-05VDC-SL-C** coil/contact set — meaning connecting it directly to a GPIO would risk both insufficient current (an ESP32 GPIO can safely source around ~12mA, while a relay coil draws many times that) and 5V feeding back into the GPIO. For this reason, a transistor handles the switching in between.

**Circuit:**
```
GPIO32 ── 330Ω (base resistor) ── 2N2222A (Base)
                                 2N2222A (Emitter) ── common GND
                                 2N2222A (Collector) ── Relay coil (−)
                                                          Relay coil (+) ── 5V
```

**How it works:** When GPIO32 goes HIGH (3.3V), a small base current flowing through the 330Ω resistor drives the 2N2222A into saturation; the collector-emitter path behaves nearly like a short circuit, and coil current flows from the 5V rail to GND — the transistor acts here as a **low-side switch**. When the GPIO is LOW, the transistor is in cutoff, no current flows through the coil, and the relay releases.

This means GPIO32 never sees 5V and never drives the coil current directly — it only switches a small base current of a few mA; the entire 5V/high-current side stays on the transistor and the separate 5V rail.

> **Known gap / recommended improvement:** There is currently **no** flyback (freewheeling) diode across the coil. Every time the relay releases, the coil's inductive back-EMF can produce a brief high-voltage spike at the transistor's collector; over time this can both wear out the 2N2222A and increase noise on the same 5V rail. The standard, inexpensive fix is to add a reverse-biased **1N4007** (or similar) diode across the coil terminals (cathode to the 5V side, anode to the collector side). Adding this is recommended — it is not present in the unit as currently delivered.

**Turnstile/lock connection:** In this delivered unit, a physical turnstile or electric lock is **not connected** — the relay contacts (NO/COM) are left open for test/demo purposes. When moving to a real installation, the turnstile/lock is designed to be connected to the relay contacts with its own separate power supply; the relay coil supply and the turnstile supply must be kept independent, with GND joined at a single point only (the same requirement is stated in §3.3 of the project specification).

### 2.6 LED / Buzzer Wiring

- **Green LED (GPIO25) and red LED (GPIO17):** each has a series **220–330Ω** resistor between the GPIO output and the LED anode (the range specified in the project specification; 330Ω was used) — to keep the LED current within the safe limits of both the GPIO and the LED (roughly 10–15mA).
- **Buzzer (GPIO33):** an active (self-oscillating) buzzer, driven directly from the GPIO — no PWM signal needed; a short beep means accepted, a long beep means denied.

### 2.7 Power Connection Summary

| Module | Powered from |
|---|---|
| ESP32, W5500, MFRC522, PCF8563, LEDs | 3.3V (LM2596 output) |
| Relay coil | 5V (main adapter, direct) |
| Relay trigger signal (GPIO32) | 3.3V logic — isolated from the 5V side by the transistor (see §2.5) |
| Turnstile/lock (in a real installation) | Its own separate supply, switched through the relay contacts |

## 3. Firmware

### 3.1 Development Environment

- VS Code + PlatformIO, Arduino framework
- Board: `esp32doit-devkit-v1`, platform `espressif32@6.10.0`
- Filesystem: LittleFS
- Custom partition table (`partitions_two_ota.csv`): two OTA slots (`ota_0` / `ota_1`, ~1.75MB each) plus a separate data partition (holds the persistent event queue and ACL files)

### 3.2 Libraries (`platformio.ini`)

| Library | Role |
|---|---|
| `OSSLibraries/Arduino_MFRC522v2` | RFID reading (the official v2 library, cloned from GitHub) |
| `arduino-libraries/Ethernet` | W5500 TCP/IP stack |
| `256dpi/MQTT` | MQTT client (QoS1, LWT, retained message support) |
| `bblanchon/ArduinoJson` | JSON encoding/decoding |
| `adafruit/RTClib` | RTC (supports both DS3231 and PCF8563) |
| `arduino-libraries/NTPClient` | Network time synchronization |

### 3.3 Module Structure

| File | Role |
|---|---|
| `src/main.cpp` | `setup()`/`loop()`, watchdog, launching the network task on a separate core |
| `src/hal/io_controller.*` | Relay/LED/buzzer/exit-button state machine — no `delay()`, `millis()`-based |
| `src/hal/rfid_reader.*` | MFRC522 reading, debounce (5s), triggering the access-event flow |
| `src/hal/rtc_service.*` | PCF8563 reading, NTP/RTC/invalid time-source management and the "dead reckoning" fallback mechanism |
| `src/domain/acl_engine.*` | Local authorization list (binary format on LittleFS), binary search, access decision |
| `src/storage/event_queue.*` | Persistent, append-only event queue, CRC16 verification, checkpointing |
| `src/network/network_manager.*` | W5500 + MQTT client, QoS1 store-and-forward, command queue |
| `src/network/ota_guard.*`, `src/network/ota_updater.*` | OTA update and its self-rollback protection |

### 3.4 Building and Flashing

```
pio run -t upload
```

(or "Upload" from the PlatformIO panel in VS Code). The serial port is auto-detected; the serial monitor runs at 115200 baud.

In `include/config.h`, each door's `DEVICE_ID`, `FLOOR_NUMBER`, `DEVICE_DIR`, and network settings (static IP, MQTT broker address) are fixed **at compile time** — **each door is flashed with its own binary; the same `.bin` cannot be uploaded to two different doors.** Adding a new door means changing these constants and rebuilding.

After the first flash, the local ACL and persistent queue start out empty; the ACL syncs automatically from the retained MQTT message sent by the backend.

## 4. Backend Summary (High-Level)

- **Django 5 + Django REST Framework**, PostgreSQL database, JWT (access/refresh) authentication, admin/operator role split
- **Python MQTT collector service** (`collector.py`) — writes to the `access_events`/`devices` tables using raw SQL
- **Eclipse Mosquitto** broker, port 1883 — no TLS/authentication (see §5)
- **Vue 3** web panel — employee/card/device management, PDKS report (CSV export), audit log, operator account management
- All services come up with a single command via `docker-compose.yml`

For detailed setup, API endpoints, the data model, and test instructions, see **`backend-django/README.md`**.

## 5. Known Limitations / Out-of-Scope Items

| Item | Status |
|---|---|
| MQTT TLS / authentication | Out of scope (deliberate decision) — the broker runs with `allow_anonymous true`, plain port 1883 |
| Door position (magnetic) sensor | Not used — optional in the project specification |
| Turnstile / electric lock | Not physically connected in this delivered unit — relay contacts are ready (see §2.5) |
| Flyback diode on the relay coil | Missing — adding a 1N4007 is recommended (see §2.5) |
| Real-time clock | PCF8563 used instead of DS3231 (sourcing issue) |
| Retained ACL message size | If the card count grows past a few thousand, a single MQTT retained message could hit the packet size limit — pagination/delta publishing may be needed eventually; with the currently allocated 16KB of RAM, up to 800 cards is deliberately left as the limit for this version |
| RC522/W5500 on the same SPI bus | Deliberately placed on separate SPI buses (VSPI/HSPI) — sharing one bus risks CS conflicts / random hangs |

## 6. References

- Original task specification: `ESP32_PDKS_Staj_Projesi.pdf`
- Backend/API details: `backend-django/README.md`
- ESP32 Technical Reference Manual and the ESP32-WROOM-32 datasheet (Espressif)
