"""Pubblicazione MQTT opzionale dei contatori (OUTPUT, non più input).

Se MQTT_ENABLED=1, pubblica su:
  <base>/<camera>/enter | /exit | /occupancy   (retained)
"""

import threading
import time

try:
    import paho.mqtt.client as mqtt
except Exception:                      # pragma: no cover
    mqtt = None

from app.config import Config


class MqttPublisher:
    def __init__(self):
        self.client = None
        self.connected = False

    def start(self):
        if not Config.MQTT_ENABLED or mqtt is None:
            print("[mqtt-out] disabilitato", flush=True)
            return
        threading.Thread(target=self._run, daemon=True,
                         name="mqtt-out").start()

    def _make(self):
        try:
            return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except Exception:
            return mqtt.Client()

    def _run(self):
        self.client = self._make()
        if Config.MQTT_USER:
            self.client.username_pw_set(Config.MQTT_USER, Config.MQTT_PASS)
        while True:
            try:
                print(f"[mqtt-out] connessione {Config.MQTT_HOST}:"
                      f"{Config.MQTT_PORT}", flush=True)
                self.client.connect(Config.MQTT_HOST, Config.MQTT_PORT, 60)
                self.connected = True
                self.client.loop_forever()
            except Exception as e:
                self.connected = False
                print(f"[mqtt-out] errore: {e}, retry 5s", flush=True)
                time.sleep(5)

    def publish_counts(self, snap):
        if not self.client or not self.connected:
            return
        base = Config.MQTT_BASE_TOPIC.rstrip("/")
        cam = Config.CAMERA
        try:
            self.client.publish(f"{base}/{cam}/enter", snap["enter"], retain=True)
            self.client.publish(f"{base}/{cam}/exit", snap["exit"], retain=True)
            self.client.publish(f"{base}/{cam}/occupancy", snap["occupancy"],
                                retain=True)
        except Exception as e:
            print(f"[mqtt-out] publish fallita: {e}", flush=True)
