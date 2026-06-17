"""Configurazioni da variabili d'ambiente Docker.

I default qui sono la base; vengono sovrascritti a runtime da settings.json
(modificabile dalla pagina Impostazioni).
"""

import os
import secrets


class Config:
    # ============ Etichetta ============
    CAMERA = os.environ.get("CAMERA_NAME", "ingresso")

    # ============ MQTT input (sorgente eventi enter/exit dall'ESP) ============
    MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
    MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
    MQTT_USER = os.environ.get("MQTT_USER", "")
    MQTT_PASS = os.environ.get("MQTT_PASS", "")
    # topic (anche wildcard +/#) da sottoscrivere — default = baseTopic firmware
    MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "peoplecounter/#")
    # token (CSV) per riconoscere enter/exit/passaggio nel topic o nel payload
    MQTT_ENTER_TOKENS = os.environ.get("MQTT_ENTER_TOKENS", "enter,in,entrata")
    MQTT_EXIT_TOKENS = os.environ.get("MQTT_EXIT_TOKENS", "exit,out,uscita")
    MQTT_PASS_TOKENS = os.environ.get("MQTT_PASS_TOKENS", "pass,passage,passaggio")

    # Mappatura di un PASSAGGIO (raggio singolo = niente direzione):
    #   alternate = alterna entrata/uscita  -> entrate ≈ uscite ≈ passaggi/2 (stima)
    #   enter     = ogni passaggio è un'entrata
    #   exit      = ogni passaggio è un'uscita
    PASSAGE_MODE = os.environ.get("PASSAGE_MODE", "alternate").lower()

    DEBUG = os.environ.get("DEBUG", "1") == "1"

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
