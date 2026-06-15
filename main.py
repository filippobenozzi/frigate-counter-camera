"""Entrypoint: subscriber MQTT (eventi ESP) + Flask web."""

from app import webhook
from app.config import Config
from app.mqtt_in import MqttIn
from app.settings import Settings
from app.storage import Store
from app.web import create_app


def banner():
    print("==================================================", flush=True)
    print(" Person Counter — MQTT (ESP people counter)", flush=True)
    print("==================================================", flush=True)
    print(f" MQTT       : {Config.MQTT_HOST}:{Config.MQTT_PORT}", flush=True)
    print(f" Topic      : {Config.MQTT_TOPIC}", flush=True)
    print(f" Enter tok  : {Config.MQTT_ENTER_TOKENS}", flush=True)
    print(f" Exit  tok  : {Config.MQTT_EXIT_TOKENS}", flush=True)
    print(f" Camera     : {Config.CAMERA}", flush=True)
    print(f" Storage    : JSON ({Config.LOG_DIR})"
          f"{' + Postgres' if Config.postgres_enabled() else ''}", flush=True)
    print(f" Webhook    : {'ON' if Config.WEBHOOK_ENABLED else 'OFF'}", flush=True)
    print(f" Auth       : {'ON (' + Config.AUTH_USER + ')' if Config.auth_enabled() else 'OFF (pubblica)'}",
          flush=True)
    print(f" Web port   : {Config.WEB_PORT}", flush=True)
    print("==================================================", flush=True)


def main():
    Settings.load()
    banner()

    store = Store()
    print(f"[init] counts iniziali: {store.snapshot()}", flush=True)

    webhook.start()

    mqtt = MqttIn(store)
    mqtt.start()

    app = create_app(store, mqtt)
    app.run(host="0.0.0.0", port=Config.WEB_PORT, threaded=True)


if __name__ == "__main__":
    main()
