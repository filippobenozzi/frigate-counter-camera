"""Runtime settings: sovrascrivono i default da env e sono persistite su file.

`settings.json` (in LOG_DIR) è la fonte di verità a runtime: caricato all'avvio,
riscritto a ogni salvataggio dalla UI.

Campi `secret` (password): in GET sono mascherati "***"; inviare "***" in POST
significa "non cambiare", stringa vuota significa "svuota". I parametri di
connessione MQTT sono `restart_needed` (la connessione è già attiva).
"""

import json
import os
import threading

from app.config import Config


EDITABLE = {
    # ===== Etichetta =====
    "CAMERA":            {"type": "str",   "group": "camera"},

    # ===== MQTT input =====
    "MQTT_HOST":         {"type": "str",    "group": "mqtt", "restart_needed": True},
    "MQTT_PORT":         {"type": "int",    "min": 1, "max": 65535, "group": "mqtt", "restart_needed": True},
    "MQTT_USER":         {"type": "str",    "group": "mqtt", "restart_needed": True},
    "MQTT_PASS":         {"type": "secret", "group": "mqtt", "restart_needed": True},
    "MQTT_TOPIC":        {"type": "str",    "group": "mqtt", "restart_needed": True},
    "MQTT_ENTER_TOKENS": {"type": "str",    "group": "mqtt"},
    "MQTT_EXIT_TOKENS":  {"type": "str",    "group": "mqtt"},
    "MQTT_PASS_TOKENS":  {"type": "str",    "group": "mqtt"},
    "PASSAGE_MODE":      {"type": "str",    "group": "mqtt"},

    # ===== PostgreSQL =====
    "DB_HOST":           {"type": "str",    "group": "postgres"},
    "DB_PORT":           {"type": "int",    "min": 1, "max": 65535, "group": "postgres"},
    "DB_NAME":           {"type": "str",    "group": "postgres"},
    "DB_USER":           {"type": "str",    "group": "postgres"},
    "DB_PASS":           {"type": "secret", "group": "postgres"},
    "DB_SCHEMA":         {"type": "str",    "group": "postgres"},
    "DB_TABLE":          {"type": "str",    "group": "postgres"},
    "DB_SSLMODE":        {"type": "str",    "group": "postgres"},

    # ===== Webhook =====
    "WEBHOOK_ENABLED":   {"type": "bool",   "group": "webhook"},
    "WEBHOOK_URL":       {"type": "url",    "group": "webhook"},
    "WEBHOOK_HEADERS":   {"type": "json",   "group": "webhook"},
    "WEBHOOK_TIMEOUT":   {"type": "float",  "min": 0.5, "max": 30, "group": "webhook"},
    "WEBHOOK_RETRY":     {"type": "int",    "min": 0,   "max": 5,  "group": "webhook"},
}

_VALID_SSLMODE = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
_VALID_PASSAGE = {"alternate", "enter", "exit"}
SECRET_MASK = "***"


def _coerce(key, raw):
    meta = EDITABLE[key]
    typ = meta["type"]
    if typ in ("str", "url", "secret"):
        v = str(raw).strip() if raw is not None else ""
        if key == "DB_SSLMODE":
            v = v.lower()
            if v and v not in _VALID_SSLMODE:
                raise ValueError(f"deve essere uno tra {sorted(_VALID_SSLMODE)}")
        elif key == "PASSAGE_MODE":
            v = v.lower()
            if v and v not in _VALID_PASSAGE:
                raise ValueError(f"deve essere uno tra {sorted(_VALID_PASSAGE)}")
        if typ == "url" and v:
            if not (v.startswith("http://") or v.startswith("https://")):
                raise ValueError("deve iniziare con http:// o https://")
            v = v.rstrip("/")
        return v
    if typ == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if typ == "json":
        if raw is None or raw == "":
            return ""
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return ""
            try:
                json.loads(s)
            except Exception as e:
                raise ValueError(f"JSON non valido: {e}")
            return s
        return json.dumps(raw)
    if typ == "int":
        v = int(float(raw))
    else:
        v = float(raw)
    lo, hi = meta.get("min"), meta.get("max")
    if lo is not None and v < lo:
        raise ValueError(f"< {lo}")
    if hi is not None and v > hi:
        raise ValueError(f"> {hi}")
    return v


def _is_secret(key):
    return EDITABLE[key]["type"] == "secret"


class Settings:
    _lock = threading.Lock()

    @classmethod
    def load(cls):
        path = Config.SETTINGS_FILE
        if not os.path.exists(path):
            print("[settings] nessun settings.json, uso default da env",
                  flush=True)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[settings] errore lettura {path}: {e}", flush=True)
            return
        applied = 0
        for k, v in data.items():
            if k not in EDITABLE:
                continue
            try:
                setattr(Config, k, _coerce(k, v))
                applied += 1
            except Exception as e:
                print(f"[settings] '{k}' non valido nel file: {e}", flush=True)
        print(f"[settings] caricati {applied} parametri da {path}", flush=True)

    @classmethod
    def current(cls, mask_secrets=True):
        out = {}
        for k in EDITABLE.keys():
            v = getattr(Config, k, None)
            if mask_secrets and _is_secret(k):
                out[k] = SECRET_MASK if v else ""
            else:
                out[k] = v
        return out

    @classmethod
    def schema(cls):
        return {k: dict(v) for k, v in EDITABLE.items()}

    @classmethod
    def update(cls, new_values: dict):
        coerced, errors = {}, {}
        for k, v in new_values.items():
            if k not in EDITABLE:
                continue
            if _is_secret(k) and v == SECRET_MASK:
                continue
            if v is None:
                continue
            try:
                coerced[k] = _coerce(k, v)
            except Exception as e:
                errors[k] = str(e)
        if errors:
            raise ValueError("; ".join(f"{k}: {e}" for k, e in errors.items()))

        restart_needed = False
        with cls._lock:
            for k, v in coerced.items():
                if getattr(Config, k, None) != v and EDITABLE[k].get("restart_needed"):
                    restart_needed = True
                setattr(Config, k, v)
            payload = cls.current(mask_secrets=False)
            tmp = Config.SETTINGS_FILE + ".tmp"
            os.makedirs(os.path.dirname(Config.SETTINGS_FILE) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
            os.replace(tmp, Config.SETTINGS_FILE)

        return {"changed": list(coerced.keys()), "restart_needed": restart_needed}
