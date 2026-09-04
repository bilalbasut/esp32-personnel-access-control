"""Kısa ömürlü tek-seferlik publish - bu trafik hacminde bağlantı maliyeti önemsiz."""
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
