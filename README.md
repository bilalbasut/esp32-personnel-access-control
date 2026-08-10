## Proje Hakkında
Bu proje, çok katlı binalar için tasarlanmış, çevrimdışı çalışabilme (offline-first) yeteneğine sahip, ESP32 tabanlı bir RFID geçiş kontrol ve Personel Devam Kontrol Sistemidir (PDKS). Sistem, ağ bağlantısı (Ethernet) veya MQTT sunucusu kopsa dahi kapı geçiş işlemlerini yerel yetki listesine (ACL) göre kesintisiz bir şekilde sürdürür. Ağ bağlantısı tekrar sağlandığında, çevrimdışıyken biriken veriler hiçbir kayıp yaşanmadan tekil olarak (MQTT QoS 1 ile) merkeze aktarılır.

## Temel Özellikler
* **Çevrimdışı Dayanıklılık (Offline-First):** Kararlar tamamen cihaz üzerinde, LittleFS veya NVS'te saklanan yetki listesi ile verilir. Ağ gecikmesi kapı açılışını bloklamaz.
* **Kalıcı Olay Kuyruğu:** Okunan her geçerli/geçersiz geçiş olayı röle tetiklenmeden önce flash belleğe (LittleFS) kaydedilir.
* **QoS 1 ve Tekilleştirme:** Sistem, kayıtları sırayla ve güvenilir şekilde gönderir. Gönderim işaretçisi yalnızca sunucudan gelen ACK mesajı ile ilerletilir.
* **Bloklamayan (Non-blocking) Tasarım:** Sistem `delay()` kullanmaz; FreeRTOS görevleri (tasks) ve `millis()` tabanlı zamanlama kullanılarak RFID okuma ve ağ bağlantı süreçleri birbirinden izole edilmiştir.
* **Uzaktan Yönetim:** Sunucudan gelen retained MQTT mesajları ile yetki listesi (ACL) cihazlarda güncellenir.

## Donanım Listesi
* ESP32-WROOM-32 DevKit v1
* W5500 Ethernet Modülü (SPI)
* MFRC522 RFID Okuyucu Modülü (13.56 MHz, HSPI)
* Mifare Classic 1K Kartlar (Test için)
* DS3231 RTC Modülü (Çevrimdışı zaman damgası için I2C, Pil yedekli)
* 1 Kanallı Röle Modülü (Optokuplörlü, 3.3V)
* Yeşil ve Kırmızı LED, Aktif Buzzer
* Çıkış Butonu ve Manyetik Kapı Kontağı (Reed Switch)
* Harici Güç: 5V/2A DC Adaptör ve AMS1117-3.3V Regülatör

## Pin Haritası (Donanım Bağlantıları)

| Modül / Sinyal | ESP32 GPIO | Arayüz | Açıklama |
| :--- | :--- | :--- | :--- |
| W5500 SCK / MISO / MOSI | 18 / 19 / 23 | VSPI | Donanım SPI |
| W5500 CS | 5 | VSPI | Boot'ta HIGH kalmalı |
| W5500 RST | 4 | GPIO | Açılışta 1 ms LOW darbesi |
| MFRC522 SCK / MISO / MOSI| 14 / 27 / 13 | HSPI | Ayrı SPI veri yolu |
| MFRC522 CS (SDA) / RST | 15 / 26 | HSPI | GPIO15 boot'ta HIGH |
| DS3231 SDA / SCL | 21 / 22 | I2C | 0x68 adresi (RTC) |
| Röle Tetikleme | 32 | Çıkış | Optokuplörlü modül |
| Buzzer | 33 | Çıkış | Kısa bip (kabul), uzun (ret) |
| LED Yeşil / Kırmızı | 25 / 17 | Çıkış | Seri direnç ile (220-330 Ω) |
| Çıkış Butonu | 35 | Giriş | Harici 10k pull-up gerekli |
| Kapı Konum Sensörü | 34 | Giriş | Harici 10k pull-up gerekli |

> *Not: MFRC522 yalnızca 3.3V ile beslenmelidir. Sistemin kararlılığı için ESP32'nin regülatörü yerine ağ ve RFID bileşenlerini AMS1117-3.3V ile beslemek önerilir.*

## Kurulum ve Derleme (PlatformIO)
1. **Gereksinimler:** Visual Studio Code ve PlatformIO IDE eklentisini kurun.
2. **Klonlama:** Bu depoyu bilgisayarınıza klonlayın.
   ```bash
   git clone <repo_url>