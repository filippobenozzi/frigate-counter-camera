"""Runtime settings: sovrascrivono i default da env e sono persistite su file.

Esempio: l'utente sposta la linea di attraversamento dalla UI -> chiamiamo
`Settings.update({'LINE_Y': 0.62})`; il nuovo valore viene scritto su
`settings.json` E assegnato a `Config.LINE_Y` (le assegnazioni a class attr
sono atomiche in Python, ok lette dal thread MQTT senza lock).
"""

import json
import os
import threading

from app.config import Config


# Chiavi modificabili dalla UI, con cast e range di validazione.
# (key, type, min, max)
EDITABLE = {
    # ---- modalità ----
    "COUNT_MODE":           ("str",   None, None),  # full_motion | line_cross
    "ENTER_DIRECTION":      ("str",   None, None),  # up | down
    "POINT_MODE":           ("str",   None, None),  # bottom | center

    # ---- linea (line_cross) ----
    "LINE_Y":               ("float", 0.0,  1.0),
    "LINE_MARGIN":          ("float", 0.0,  0.45),

    # ---- ROI (rettangolo "porta") ----
    "MOTION_X1":            ("float", 0.0,  1.0),
    "MOTION_X2":            ("float", 0.0,  1.0),
    "MOTION_Y1":            ("float", 0.0,  1.0),
    "MOTION_Y2":            ("float", 0.0,  1.0),

    # ---- soglie movimento (full_motion) ----
    "MOTION_MIN_POINTS":    ("int",   2,    50),
    "MOTION_MIN_DELTA_Y":   ("float", 0.0,  1.0),
    "MOTION_MIN_SPAN_Y":    ("float", 0.0,  1.0),
    "MOTION_MIN_NET_RATIO": ("float", 0.0,  1.0),

    # ---- jitter ----
    "JITTER_DISTANCE":      ("float", 0.0,  0.2),

    # ---- tracking ----
    "TRACK_TTL":            ("float", 1.0,  300.0),
    "TRACK_POINTS_MAX":     ("int",   10,   2000),
}

_VALID_COUNT_MODES = {"full_motion", "line_cross"}
_VALID_DIRECTIONS  = {"up", "down"}
_VALID_POINT_MODES = {"bottom", "center"}


def _coerce(key, raw):
    """Converte raw nel tipo giusto e valida i range."""
    typ, lo, hi = EDITABLE[key]
    if typ == "str":
        v = str(raw).strip().lower()
        if key == "COUNT_MODE" and v not in _VALID_COUNT_MODES:
            raise ValueError(f"COUNT_MODE must be one of {_VALID_COUNT_MODES}")
        if key == "ENTER_DIRECTION" and v not in _VALID_DIRECTIONS:
            raise ValueError(f"ENTER_DIRECTION must be one of {_VALID_DIRECTIONS}")
        if key == "POINT_MODE" and v not in _VALID_POINT_MODES:
            raise ValueError(f"POINT_MODE must be one of {_VALID_POINT_MODES}")
        return v
    if typ == "int":
        v = int(float(raw))
    else:
        v = float(raw)
    if lo is not None and v < lo:
        raise ValueError(f"{key} < {lo}")
    if hi is not None and v > hi:
        raise ValueError(f"{key} > {hi}")
    return v


class Settings:
    _lock = threading.Lock()

    @classmethod
    def load(cls):
        """All'avvio: legge settings.json e sovrascrive Config."""
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

        applied = []
        for k, v in data.items():
            if k not in EDITABLE:
                continue
            try:
                value = _coerce(k, v)
            except Exception as e:
                print(f"[settings] '{k}' non valido in file: {e}", flush=True)
                continue
            setattr(Config, k, value)
            applied.append(f"{k}={value}")
        print(f"[settings] caricati: {', '.join(applied) or 'nessuno'}",
              flush=True)

    @classmethod
    def current(cls):
        """Snapshot di TUTTE le chiavi modificabili."""
        return {k: getattr(Config, k) for k in EDITABLE.keys()}

    @classmethod
    def update(cls, new_values: dict):
        """Aggiorna in memoria + persiste su disco. Ritorna le chiavi cambiate."""
        coerced = {}
        for k, v in new_values.items():
            if k not in EDITABLE:
                continue
            if v is None or v == "":
                continue
            try:
                coerced[k] = _coerce(k, v)
            except Exception as e:
                raise ValueError(f"{k}: {e}")

        # sanity check: MOTION_X1 < MOTION_X2, MOTION_Y1 < MOTION_Y2
        x1 = coerced.get("MOTION_X1", Config.MOTION_X1)
        x2 = coerced.get("MOTION_X2", Config.MOTION_X2)
        y1 = coerced.get("MOTION_Y1", Config.MOTION_Y1)
        y2 = coerced.get("MOTION_Y2", Config.MOTION_Y2)
        if x1 >= x2:
            raise ValueError("MOTION_X1 deve essere < MOTION_X2")
        if y1 >= y2:
            raise ValueError("MOTION_Y1 deve essere < MOTION_Y2")

        with cls._lock:
            for k, v in coerced.items():
                setattr(Config, k, v)
            # persisti SEMPRE il dump completo
            payload = cls.current()
            tmp = Config.SETTINGS_FILE + ".tmp"
            try:
                os.makedirs(os.path.dirname(Config.SETTINGS_FILE) or ".",
                            exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
                os.replace(tmp, Config.SETTINGS_FILE)
            except Exception as e:
                print(f"[settings] errore salvataggio: {e}", flush=True)
                raise

        return list(coerced.keys())
