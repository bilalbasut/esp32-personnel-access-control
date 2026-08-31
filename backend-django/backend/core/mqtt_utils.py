"""Thin wrapper around paho-mqtt's one-shot publish helper, used for
transient command publishes (open/sync/reboot/settime/ota) that server.js
sent over its single long-lived mqtt client. A short-lived connection per
publish is simpler to reason about from a request/response web process and
is cheap enough for this traffic volume."""
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
