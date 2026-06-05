"""Entrypoint: avvia cattura RTSP + pipeline detection/tracking + web."""

from app import webhook
from app.config import Config
from app.mqtt_out import MqttPublisher
from app.pipeline import Pipeline
from app.settings import Settings
from app.storage import Store
from app.web import create_app


def banner():
    print("==================================================", flush=True)
    print(" Person Counter — YOLOv8 + RTSP (no Frigate)", flush=True)
    print("==================================================", flush=True)
    print(f" RTSP       : {Config.RTSP_URL or '(NON configurato!)'}", flush=True)
    print(f" Transport  : {Config.RTSP_TRANSPORT}", flush=True)
    print(f" Modello    : {Config.MODEL_PATH}", flush=True)
    print(f" Detect     : {Config.DETECT_FPS} fps  conf={Config.DETECT_CONF}  "
          f"input={Config.DETECT_INPUT_SIZE}", flush=True)
    print(f" Tracking   : max_age={Config.TRACK_MAX_AGE} "
          f"min_hits={Config.TRACK_MIN_HITS} iou={Config.TRACK_IOU}", flush=True)
    print(f" Camera     : {Config.CAMERA}", flush=True)
    print(f" Direzione  : enter = {Config.ENTER_DIRECTION}  "
          f"point={Config.POINT_MODE}", flush=True)
    print(f" Linea Y    : {Config.LINE_Y} ± {Config.LINE_MARGIN}", flush=True)
    print(f" ROI        : X[{Config.MOTION_X1}-{Config.MOTION_X2}] "
          f"Y[{Config.MOTION_Y1}-{Config.MOTION_Y2}]", flush=True)
    print(f" Storage    : JSON ({Config.LOG_DIR})"
          f"{' + Postgres' if Config.postgres_enabled() else ''}", flush=True)
    print(f" MQTT out   : {'ON' if Config.MQTT_ENABLED else 'OFF'}", flush=True)
    print(f" Webhook    : {'ON' if Config.WEBHOOK_ENABLED else 'OFF'}", flush=True)
    print(f" Auth       : {'ON (' + Config.AUTH_USER + ')' if Config.auth_enabled() else 'OFF (pubblica)'}",
          flush=True)
    print(f" Web port   : {Config.WEB_PORT}", flush=True)
    print("==================================================", flush=True)


def main():
    # carica override runtime PRIMA di tutto (capture/detector leggono Config)
    Settings.load()
    banner()

    store = Store()
    print(f"[init] counts iniziali: {store.snapshot()}", flush=True)

    webhook.start()

    mqtt_pub = MqttPublisher()
    mqtt_pub.start()

    pipeline = Pipeline(store, mqtt_pub=mqtt_pub)
    pipeline.start()

    app = create_app(store, pipeline)
    app.run(host="0.0.0.0", port=Config.WEB_PORT, threaded=True)


if __name__ == "__main__":
    main()
