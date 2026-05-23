"""Tutte le configurazioni leggibili da variabili d'ambiente Docker."""

import os
import secrets


class Config:
    # ---- MQTT ----
    MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
    MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
    MQTT_USER = os.environ.get("MQTT_USER", "")
    MQTT_PASS = os.environ.get("MQTT_PASS", "")

    # ---- Camera ----
    CAMERA = os.environ.get("CAMERA_NAME", "ingresso")
    FRAME_W = int(os.environ.get("FRAME_WIDTH", "1280"))
    FRAME_H = int(os.environ.get("FRAME_HEIGHT", "720"))

    # ---- Detection ----
    ENTER_DIRECTION = os.environ.get("ENTER_DIRECTION", "up").lower()
    POINT_MODE = os.environ.get("POINT_MODE", "bottom").lower()
    DEBUG = os.environ.get("DEBUG", "1") == "1"

    # full_motion = delta_y + span_y + net_ratio (logica vecchia)
    # line_cross  = la persona DEVE attraversare la linea da un lato all'altro
    COUNT_MODE = os.environ.get("COUNT_MODE", "line_cross").lower()

    TRACK_TTL = float(os.environ.get("TRACK_TTL", "30"))
    TRACK_POINTS_MAX = int(os.environ.get("TRACK_POINTS_MAX", "120"))

    MOTION_X1 = float(os.environ.get("MOTION_X1", "0.20"))
    MOTION_X2 = float(os.environ.get("MOTION_X2", "0.92"))
    MOTION_Y1 = float(os.environ.get("MOTION_Y1", "0.05"))
    MOTION_Y2 = float(os.environ.get("MOTION_Y2", "0.98"))

    # parametri per modalità line_cross
    LINE_Y         = float(os.environ.get("LINE_Y", "0.50"))
    LINE_MARGIN    = float(os.environ.get("LINE_MARGIN", "0.08"))

    MOTION_MIN_POINTS = int(os.environ.get("MOTION_MIN_POINTS", "4"))
    MOTION_MIN_DELTA_Y = float(os.environ.get("MOTION_MIN_DELTA_Y", "0.16"))
    MOTION_MIN_SPAN_Y = float(os.environ.get("MOTION_MIN_SPAN_Y", "0.20"))
    MOTION_MIN_NET_RATIO = float(os.environ.get("MOTION_MIN_NET_RATIO", "0.45"))

    JITTER_DISTANCE = float(os.environ.get("JITTER_DISTANCE", "0.015"))
    REQUIRED_ZONE = os.environ.get("REQUIRED_ZONE", "").strip()

    # ---- Frigate (per snapshot) ----
    FRIGATE_URL = os.environ.get("FRIGATE_URL", "").rstrip("/")
    SNAPSHOT_REFRESH_SEC = float(os.environ.get("SNAPSHOT_REFRESH_SEC", "3"))

    # ---- Webhook (notifica per ogni enter/exit) ----
    WEBHOOK_ENABLED = os.environ.get("WEBHOOK_ENABLED", "0") == "1"
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").strip()
    WEBHOOK_HEADERS = os.environ.get("WEBHOOK_HEADERS", "").strip()   # JSON string
    WEBHOOK_TIMEOUT = float(os.environ.get("WEBHOOK_TIMEOUT", "4"))
    WEBHOOK_RETRY = int(os.environ.get("WEBHOOK_RETRY", "1"))

    # ---- Storage JSON (sempre attivo) ----
    LOG_DIR = os.environ.get("LOG_DIR", "/data")
    COUNTS_FILE = os.environ.get("COUNTS_FILE", f"{LOG_DIR}/counts.json")
    EVENTS_FILE = os.environ.get("EVENTS_FILE", f"{LOG_DIR}/events.jsonl")
    SETTINGS_FILE = os.environ.get("SETTINGS_FILE", f"{LOG_DIR}/settings.json")

    # ---- Auth ----
    AUTH_USER = os.environ.get("AUTH_USER", "").strip()
    AUTH_PASS = os.environ.get("AUTH_PASS", "")
    # se SECRET_KEY non è settata, ne generiamo una random (le sessioni
    # vengono però invalidate ad ogni restart del container)
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "7"))

    # ---- Postgres (opzionale) ----
    DB_HOST = os.environ.get("DB_HOST", "").strip()
    DB_PORT = int(os.environ.get("DB_PORT", "5432"))
    DB_NAME = os.environ.get("DB_NAME", "").strip()
    DB_USER = os.environ.get("DB_USER", "").strip()
    DB_PASS = os.environ.get("DB_PASS", "")
    DB_SCHEMA = os.environ.get("DB_SCHEMA", "public")
    DB_TABLE = os.environ.get("DB_TABLE", "counter_events")
    DB_SSLMODE = os.environ.get("DB_SSLMODE", "prefer")

    # ---- Web ----
    WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))

    @classmethod
    def postgres_enabled(cls) -> bool:
        return bool(cls.DB_HOST and cls.DB_NAME and cls.DB_USER)

    @classmethod
    def auth_enabled(cls) -> bool:
        return bool(cls.AUTH_USER and cls.AUTH_PASS)
