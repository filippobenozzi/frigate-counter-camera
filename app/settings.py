"""Runtime settings: sovrascrivono i default da env e sono persistite su file.

Il file `settings.json` (in LOG_DIR) è la fonte di verità a runtime: viene
caricato all'avvio, e ogni volta che l'utente salva dalla UI viene
sovrascritto con il dump completo dei parametri editabili.

I campi `secret` (password) sono ritornati come "***" nelle GET pubbliche;
quando il client invia "***" come valore in una POST, viene interpretato come
"non cambiare". Stringa vuota invece equivale a "svuotare".

Alcuni cambi richiedono restart del container (es. host MQTT, porta web):
sono marcati `restart_needed=True` e l'API lo segnala al client.
"""

import json
import os
import threading

from app.config import Config


# Tabella unica di tutti i parametri modificabili da UI.
# Ogni voce: type, min, max, group, restart_needed, secret
# - type: "str" | "int" | "float" | "bool" | "url" | "secret" | "json"
# - group: stringa per raggruppare nella UI
# - restart_needed: True se cambiarlo richiede restart del container
# - secret: True se va mascherato in GET (password etc.)
EDITABLE = {
    # ===== Modalità di conteggio =====
    "COUNT_MODE":           {"type": "str",   "group": "detection"},
    "ENTER_DIRECTION":      {"type": "str",   "group": "detection"},
    "POINT_MODE":           {"type": "str",   "group": "detection"},

    # ===== Linea =====
    "LINE_Y":               {"type": "float", "min": 0.0, "max": 1.0,  "group": "line"},
    "LINE_MARGIN":          {"type": "float", "min": 0.0, "max": 0.45, "group": "line"},

    # ===== ROI =====
    "MOTION_X1":            {"type": "float", "min": 0.0, "max": 1.0, "group": "roi"},
    "MOTION_X2":            {"type": "float", "min": 0.0, "max": 1.0, "group": "roi"},
    "MOTION_Y1":            {"type": "float", "min": 0.0, "max": 1.0, "group": "roi"},
    "MOTION_Y2":            {"type": "float", "min": 0.0, "max": 1.0, "group": "roi"},

    # ===== Soglie full_motion =====
    "MOTION_MIN_POINTS":    {"type": "int",   "min": 2,   "max": 50,   "group": "thresholds"},
    "MOTION_MIN_DELTA_Y":   {"type": "float", "min": 0.0, "max": 1.0, "group": "thresholds"},
    "MOTION_MIN_SPAN_Y":    {"type": "float", "min": 0.0, "max": 1.0, "group": "thresholds"},
    "MOTION_MIN_NET_RATIO": {"type": "float", "min": 0.0, "max": 1.0, "group": "thresholds"},

    # ===== Tracking =====
    "JITTER_DISTANCE":      {"type": "float", "min": 0.0, "max": 0.2,   "group": "tracking"},
    "TRACK_TTL":            {"type": "float", "min": 1.0, "max": 300.0, "group": "tracking"},
    "TRACK_POINTS_MAX":     {"type": "int",   "min": 10,  "max": 2000,  "group": "tracking"},

    # ===== Camera =====
    "CAMERA":               {"type": "str",   "group": "camera"},
    "FRAME_W":              {"type": "int",   "min": 320,  "max": 7680, "group": "camera"},
    "FRAME_H":              {"type": "int",   "min": 240,  "max": 4320, "group": "camera"},
    "REQUIRED_ZONE":        {"type": "str",   "group": "camera"},

    # ===== MQTT (restart) =====
    "MQTT_HOST":            {"type": "str",    "group": "mqtt", "restart_needed": True},
    "MQTT_PORT":            {"type": "int",    "min": 1, "max": 65535,
                             "group": "mqtt", "restart_needed": True},
    "MQTT_USER":            {"type": "str",    "group": "mqtt", "restart_needed": True},
    "MQTT_PASS":            {"type": "secret", "group": "mqtt", "restart_needed": True},

    # ===== Frigate (snapshot) =====
    "FRIGATE_URL":          {"type": "url",   "group": "frigate"},
    "SNAPSHOT_REFRESH_SEC": {"type": "float", "min": 0.5, "max": 60, "group": "frigate"},

    # ===== PostgreSQL =====
    "DB_HOST":              {"type": "str",    "group": "postgres"},
    "DB_PORT":              {"type": "int",    "min": 1, "max": 65535, "group": "postgres"},
    "DB_NAME":              {"type": "str",    "group": "postgres"},
    "DB_USER":              {"type": "str",    "group": "postgres"},
    "DB_PASS":              {"type": "secret", "group": "postgres"},
    "DB_SCHEMA":            {"type": "str",    "group": "postgres"},
    "DB_TABLE":             {"type": "str",    "group": "postgres"},
    "DB_SSLMODE":           {"type": "str",    "group": "postgres"},

    # ===== Webhook =====
    "WEBHOOK_ENABLED":      {"type": "bool",   "group": "webhook"},
    "WEBHOOK_URL":          {"type": "url",    "group": "webhook"},
    "WEBHOOK_HEADERS":      {"type": "json",   "group": "webhook"},  # dict serializzato
    "WEBHOOK_TIMEOUT":      {"type": "float",  "min": 0.5, "max": 30, "group": "webhook"},
    "WEBHOOK_RETRY":        {"type": "int",    "min": 0,   "max": 5,  "group": "webhook"},
}

_VALID_COUNT_MODES = {"full_motion", "line_cross"}
_VALID_DIRECTIONS  = {"up", "down"}
_VALID_POINT_MODES = {"bottom", "center"}
_VALID_SSLMODE     = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}

SECRET_MASK = "***"


def _coerce(key, raw):
    meta = EDITABLE[key]
    typ = meta["type"]
    if typ in ("str", "url", "secret"):
        v = str(raw).strip() if raw is not None else ""
        if key == "COUNT_MODE":
            v = v.lower()
            if v and v not in _VALID_COUNT_MODES:
                raise ValueError(f"deve essere uno tra {sorted(_VALID_COUNT_MODES)}")
        elif key == "ENTER_DIRECTION":
            v = v.lower()
            if v and v not in _VALID_DIRECTIONS:
                raise ValueError(f"deve essere uno tra {sorted(_VALID_DIRECTIONS)}")
        elif key == "POINT_MODE":
            v = v.lower()
            if v and v not in _VALID_POINT_MODES:
                raise ValueError(f"deve essere uno tra {sorted(_VALID_POINT_MODES)}")
        elif key == "DB_SSLMODE":
            v = v.lower()
            if v and v not in _VALID_SSLMODE:
                raise ValueError(f"deve essere uno tra {sorted(_VALID_SSLMODE)}")
        elif typ == "url" and v:
            if not (v.startswith("http://") or v.startswith("https://")):
                raise ValueError("deve iniziare con http:// o https://")
            v = v.rstrip("/")
        return v
    if typ == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        return s in ("1", "true", "yes", "on")
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
    # int / float numeric
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
        """All'avvio: legge settings.json e sovrascrive Config.*."""
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
                value = _coerce(k, v)
            except Exception as e:
                print(f"[settings] '{k}' non valido nel file: {e}",
                      flush=True)
                continue
            setattr(Config, k, value)
            applied += 1
        print(f"[settings] caricati {applied} parametri da {path}",
              flush=True)

    @classmethod
    def current(cls, mask_secrets=True):
        """Snapshot di TUTTE le chiavi modificabili."""
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
        """Schema dei campi editabili (per la UI)."""
        return {k: dict(v) for k, v in EDITABLE.items()}

    @classmethod
    def update(cls, new_values: dict):
        """Aggiorna in memoria + persiste su disco.

        Ritorna dict {changed: [...], restart_needed: bool}.
        """
        coerced = {}
        errors = {}

        for k, v in new_values.items():
            if k not in EDITABLE:
                continue
            # campi secret: "***" significa "non cambiare"
            if _is_secret(k) and v == SECRET_MASK:
                continue
            # None o omesso: non cambiare
            if v is None:
                continue
            try:
                coerced[k] = _coerce(k, v)
            except Exception as e:
                errors[k] = str(e)

        if errors:
            raise ValueError("; ".join(f"{k}: {e}" for k, e in errors.items()))

        # sanity checks incrociati
        x1 = coerced.get("MOTION_X1", Config.MOTION_X1)
        x2 = coerced.get("MOTION_X2", Config.MOTION_X2)
        y1 = coerced.get("MOTION_Y1", Config.MOTION_Y1)
        y2 = coerced.get("MOTION_Y2", Config.MOTION_Y2)
        if x1 >= x2:
            raise ValueError("MOTION_X1 deve essere < MOTION_X2")
        if y1 >= y2:
            raise ValueError("MOTION_Y1 deve essere < MOTION_Y2")

        restart_needed = False

        with cls._lock:
            for k, v in coerced.items():
                old = getattr(Config, k, None)
                if old != v and EDITABLE[k].get("restart_needed"):
                    restart_needed = True
                setattr(Config, k, v)

            payload = cls.current(mask_secrets=False)
            tmp = Config.SETTINGS_FILE + ".tmp"
            os.makedirs(os.path.dirname(Config.SETTINGS_FILE) or ".",
                        exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False,
                          sort_keys=True)
            os.replace(tmp, Config.SETTINGS_FILE)

        return {
            "changed": list(coerced.keys()),
            "restart_needed": restart_needed,
        }
