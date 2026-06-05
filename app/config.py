"""Configurazioni leggibili da variabili d'ambiente Docker.

I default qui sono la base; vengono sovrascritti a runtime da settings.json
(modificabile dalla pagina Impostazioni).
"""

import os
import secrets


class Config:
    # ============ Sorgente video RTSP / RTSPS ============
    RTSP_URL = os.environ.get("RTSP_URL", "").strip()
    RTSP_TRANSPORT = os.environ.get("RTSP_TRANSPORT", "tcp").lower()   # tcp | udp
    CAPTURE_RECONNECT_SEC = float(os.environ.get("CAPTURE_RECONNECT_SEC", "3"))
    CAPTURE_TIMEOUT_SEC = float(os.environ.get("CAPTURE_TIMEOUT_SEC", "5"))

    # ============ Detection (YOLOv8n ONNX, solo CPU) ============
    MODEL_PATH = os.environ.get("MODEL_PATH", "/models/model.onnx")
    DETECT_FPS = float(os.environ.get("DETECT_FPS", "10"))
    DETECT_INPUT_SIZE = int(os.environ.get("DETECT_INPUT_SIZE", "640"))
    # vista dall'alto/fisheye/IR: soglia bassa per rilevare prima
    DETECT_CONF = float(os.environ.get("DETECT_CONF", "0.25"))
    DETECT_IOU_NMS = float(os.environ.get("DETECT_IOU_NMS", "0.5"))
    PERSON_CLASS_ID = int(os.environ.get("PERSON_CLASS_ID", "0"))
    MAX_DETECTIONS = int(os.environ.get("MAX_DETECTIONS", "50"))
    ORT_THREADS = int(os.environ.get("ORT_THREADS", "0"))             # 0 = auto

    # ============ Tracking (SORT) ============
    TRACK_MAX_AGE = int(os.environ.get("TRACK_MAX_AGE", "15"))
    # min_hits basso = conferma rapida = conta anche i transiti veloci
    TRACK_MIN_HITS = int(os.environ.get("TRACK_MIN_HITS", "2"))
    TRACK_IOU = float(os.environ.get("TRACK_IOU", "0.3"))

    # ============ Camera (solo etichetta) ============
    CAMERA = os.environ.get("CAMERA_NAME", "ingresso")

    # ============ Conteggio (linea + ROI) ============
    ENTER_DIRECTION = os.environ.get("ENTER_DIRECTION", "up").lower()  # up | down
    POINT_MODE = os.environ.get("POINT_MODE", "bottom").lower()        # bottom | center
    LINE_Y = float(os.environ.get("LINE_Y", "0.50"))
    LINE_MARGIN = float(os.environ.get("LINE_MARGIN", "0.08"))
    MOTION_X1 = float(os.environ.get("MOTION_X1", "0.05"))
    MOTION_X2 = float(os.environ.get("MOTION_X2", "0.95"))
    MOTION_Y1 = float(os.environ.get("MOTION_Y1", "0.05"))
    MOTION_Y2 = float(os.environ.get("MOTION_Y2", "0.95"))

    # ============ Overlay / snapshot ============
    DRAW_OVERLAY = os.environ.get("DRAW_OVERLAY", "1") == "1"
    JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "75"))
    SNAPSHOT_REFRESH_SEC = float(os.environ.get("SNAPSHOT_REFRESH_SEC", "2"))
    DEBUG = os.environ.get("DEBUG", "1") == "1"

    # ============ MQTT output (opzionale) ============
    MQTT_ENABLED = os.environ.get("MQTT_ENABLED", "0") == "1"
    MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
    MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
    MQTT_USER = os.environ.get("MQTT_USER", "")
    MQTT_PASS = os.environ.get("MQTT_PASS", "")
    MQTT_BASE_TOPIC = os.environ.get("MQTT_BASE_TOPIC", "counter")

    # ============ Webhook (POST ad ogni enter/exit) ============
    WEBHOOK_ENABLED = os.environ.get("WEBHOOK_ENABLED", "0") == "1"
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
    WEBHOOK_HEADERS = os.environ.get("WEBHOOK_HEADERS", "").strip()    # JSON string
    WEBHOOK_TIMEOUT = float(os.environ.get("WEBHOOK_TIMEOUT", "4"))
    WEBHOOK_RETRY = int(os.environ.get("WEBHOOK_RETRY", "1"))

    # ============ Storage JSON (sempre attivo) ============
    LOG_DIR = os.environ.get("LOG_DIR", "/data")
    COUNTS_FILE = os.environ.get("COUNTS_FILE", f"{LOG_DIR}/counts.json")
    EVENTS_FILE = os.environ.get("EVENTS_FILE", f"{LOG_DIR}/events.jsonl")
    SETTINGS_FILE = os.environ.get("SETTINGS_FILE", f"{LOG_DIR}/settings.json")

    # ============ Auth ============
    AUTH_USER = os.environ.get("AUTH_USER", "").strip()
    AUTH_PASS = os.environ.get("AUTH_PASS", "")
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "7"))

    # ============ Postgres (opzionale) ============
    DB_HOST = os.environ.get("DB_HOST", "").strip()
    DB_PORT = int(os.environ.get("DB_PORT", "5432"))
    DB_NAME = os.environ.get("DB_NAME", "").strip()
    DB_USER = os.environ.get("DB_USER", "").strip()
    DB_PASS = os.environ.get("DB_PASS", "")
    DB_SCHEMA = os.environ.get("DB_SCHEMA", "public")
    DB_TABLE = os.environ.get("DB_TABLE", "counter_events")
    DB_SSLMODE = os.environ.get("DB_SSLMODE", "prefer")

    # ============ Web ============
    WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))

    @classmethod
    def postgres_enabled(cls) -> bool:
        return bool(cls.DB_HOST and cls.DB_NAME and cls.DB_USER)

    @classmethod
    def auth_enabled(cls) -> bool:
        return bool(cls.AUTH_USER and cls.AUTH_PASS)

    @classmethod
    def rtsp_configured(cls) -> bool:
        return bool(cls.RTSP_URL)
