"""Entrypoint: avvia MQTT listener in un thread e poi la Flask app."""

import threading

from app import mqtt_listener
from app.config import Config
from app.storage import Store
from app.tracker import Tracker
from app.web import create_app


def banner():
    print("==============================================", flush=True)
    print(" Frigate Person Counter — v2", flush=True)
    print("==============================================", flush=True)
    print(f" MQTT      : {Config.MQTT_HOST}:{Config.MQTT_PORT}", flush=True)
    print(f" Camera    : {Config.CAMERA}", flush=True)
    print(f" Frame     : {Config.FRAME_W}x{Config.FRAME_H}", flush=True)
    print(f" Direzione : enter = {Config.ENTER_DIRECTION}", flush=True)
    print(f" Point     : {Config.POINT_MODE}", flush=True)
    print(f" ROI X     : {Config.MOTION_X1} → {Config.MOTION_X2}", flush=True)
    print(f" ROI Y     : {Config.MOTION_Y1} → {Config.MOTION_Y2}", flush=True)
    print(f" Storage   : JSON ({Config.LOG_DIR}) "
          f"{'+ Postgres' if Config.postgres_enabled() else ''}", flush=True)
    print(f" Auth      : {'ON (' + Config.AUTH_USER + ')' if Config.auth_enabled() else 'OFF (pubblica)'}",
          flush=True)
    print(f" Web port  : {Config.WEB_PORT}", flush=True)
    if Config.REQUIRED_ZONE:
        print(f" Zona      : {Config.REQUIRED_ZONE}", flush=True)
    print("==============================================", flush=True)


def main():
    banner()

    store = Store()
    tracker = Tracker()

    print(f"[init] counts iniziali: {store.snapshot()}", flush=True)

    threading.Thread(
        target=mqtt_listener.run,
        args=(store, tracker),
        daemon=True,
        name="mqtt-listener",
    ).start()

    app = create_app(store, tracker)
    app.run(host="0.0.0.0", port=Config.WEB_PORT, threaded=True)


if __name__ == "__main__":
    main()
