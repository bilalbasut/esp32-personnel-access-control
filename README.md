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
