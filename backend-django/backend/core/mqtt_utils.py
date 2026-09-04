"""paho-mqtt'nin tek seferlik publish yardımcısı üzerine ince bir sarmalayıcı
- server.js'in tek, uzun ömürlü mqtt client'ı üzerinden gönderdiği geçici
komut publish'leri (open/sync/reboot/settime/ota) için kullanılıyor. Bir
request/response web sürecinden düşünmek için publish başına kısa ömürlü bir
bağlantı daha basit, ve bu trafik hacmi için maliyeti önemsiz."""
import paho.mqtt.publish as mqtt_publish
from django.conf import settings


def publish(topic, payload, qos=1, retain=False):
    mqtt_publish.single(
        topic,
        payload=payload,
        qos=qos,
        retain=retain,
        hostname=settings.MQTT_HOST,
        port=settings.MQTT_PORT,
    )
