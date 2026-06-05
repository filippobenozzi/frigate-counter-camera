# Configurazione

Due livelli di priorità:

1. **Variabili d'ambiente Docker** — caricate all'avvio, sono i **default**
2. **`/data/settings.json`** — sovrascrive le env, modificabile dalla UI

Salvando dalla pagina **Impostazioni**, `settings.json` viene riscritto e i
nuovi valori entrano in vigore subito, tranne quelli marcati *richiede restart*.

---

## Sorgente video (RTSP / RTSPS)

| Env | Default | UI | Note |
|---|---|---|---|
| `RTSP_URL` | *(vuoto, obbligatorio)* | sì (restart) | `rtsp://` o `rtsps://`. Consigliato un **substream** a bassa risoluzione |
| `RTSP_TRANSPORT` | `tcp` | sì (restart) | `tcp` (affidabile) o `udp` |
| `CAPTURE_TIMEOUT_SEC` | `5` | sì (restart) | timeout lettura stream |
| `CAPTURE_RECONNECT_SEC` | `3` | sì (restart) | attesa prima di riconnettere |

La cattura gira in un thread che tiene solo l'ultimo frame e si **riconnette
automaticamente** se lo stream cade.

---

## Detection (YOLOv8n ONNX, CPU)

| Env | Default | UI | Note |
|---|---|---|---|
| `MODEL_PATH` | `/models/yolov8n.onnx` | sì (restart) | file ONNX; montane uno tuo se vuoi |
| `DETECT_FPS` | `8` | sì | detection al secondo (bilancia CPU/reattività) |
| `DETECT_CONF` | `0.35` | sì | soglia confidenza persona (alza = meno falsi positivi) |
| `DETECT_IOU_NMS` | `0.5` | sì | soppressione box sovrapposti |
| `DETECT_INPUT_SIZE` | `640` | sì (restart) | lato input della rete |
| `MAX_DETECTIONS` | `50` | sì | persone max per frame |
| `ORT_THREADS` | `0` | sì (restart) | core per l'inferenza (0=auto; su NUC 2-4) |
| `PERSON_CLASS_ID` | `0` | env | classe COCO "person" |

---

## Tracking (SORT)

| Env | Default | UI | Note |
|---|---|---|---|
| `TRACK_MAX_AGE` | `15` | sì (restart) | frame di tolleranza con persona "persa" |
| `TRACK_MIN_HITS` | `3` | sì (restart) | frame minimi per confermare (anti-flicker) |
| `TRACK_IOU` | `0.3` | sì (restart) | sovrapposizione minima per associare lo stesso id |

---

## Conteggio (linea + ROI)

| Env | Default | UI | Note |
|---|---|---|---|
| `CAMERA_NAME` | `ingresso` | sì | etichetta nei dati / topic MQTT |
| `ENTER_DIRECTION` | `up` | sì | `up` = entrare = dal basso verso l'alto |
| `POINT_MODE` | `bottom` | sì | `bottom` = piedi (consigliato), `center` = centro box |
| `LINE_Y` | `0.50` | sì | posizione verticale linea 0..1 |
| `LINE_MARGIN` | `0.08` | sì | "zona morta": chi non la supera non conta |
| `MOTION_X1/X2/Y1/Y2` | `0.05/0.95/0.05/0.95` | sì | rettangolo ROI; i punti fuori sono ignorati |

**Logica**: per ogni persona si segue da che lato della linea sta. Conta solo
quando passa da `LINE_Y - LINE_MARGIN` a `LINE_Y + LINE_MARGIN` (o viceversa)
mentre è dentro la ROI. Avanti/indietro nella zona morta → nessun conteggio.

---

## Overlay / snapshot

| Env | Default | UI |
|---|---|---|
| `DRAW_OVERLAY` | `1` | sì |
| `JPEG_QUALITY` | `75` | sì |
| `SNAPSHOT_REFRESH_SEC` | `2` | sì |

Lo snapshot della pagina Impostazioni mostra il frame con i box delle persone,
la linea e la ROI disegnati dal server.

---

## MQTT output (opzionale)

| Env | Default | UI |
|---|---|---|
| `MQTT_ENABLED` | `0` | sì (restart) |
| `MQTT_HOST` | `127.0.0.1` | sì (restart) |
| `MQTT_PORT` | `1883` | sì (restart) |
| `MQTT_USER` / `MQTT_PASS` | *(vuoto)* | sì (restart) |
| `MQTT_BASE_TOPIC` | `counter` | sì (restart) |

Se abilitato, pubblica (retained):
`<base>/<camera>/enter`, `/exit`, `/occupancy`.

---

## Webhook (opzionale)

| Env | Default | UI |
|---|---|---|
| `WEBHOOK_ENABLED` | `0` | sì |
| `WEBHOOK_URL` | *(vuoto)* | sì |
| `WEBHOOK_HEADERS` | *(vuoto)* | sì — JSON es. `{"Authorization":"Bearer xxx"}` |
| `WEBHOOK_TIMEOUT` | `4` | sì |
| `WEBHOOK_RETRY` | `1` | sì |

### Payload (POST ad ogni enter/exit)

```json
{
  "event": "enter", "camera": "ingresso",
  "ts": 1716470000.123, "datetime": "2026-05-23 18:42:13",
  "occupancy": 4, "enter_total": 1247, "exit_total": 1243,
  "method": "yolo_line", "event_id": "1716470000-42",
  "start": {"x": 0.50, "y": 0.82}, "end": {"x": 0.49, "y": 0.18},
  "reason": "cross movement=up y=0.176 line=0.50 margin=0.08"
}
```

L'invio è fire-and-forget in un thread separato: anche se il webhook è lento o
down, il conteggio non si blocca. Test rapido con
[webhook.site](https://webhook.site) + bottone *Invia evento di test*.

---

## PostgreSQL (opzionale)

| Env | Default | UI |
|---|---|---|
| `DB_HOST` / `DB_PORT` | *(vuoto)* / `5432` | sì |
| `DB_NAME` / `DB_USER` / `DB_PASS` | *(vuoto)* | sì |
| `DB_SCHEMA` / `DB_TABLE` | `public` / `counter_events` | sì |
| `DB_SSLMODE` | `prefer` | sì |

Tutti vuoti → solo `events.jsonl`. Compilati → scrittura su JSON **e** Postgres.
Riconnessione a caldo al salvataggio. Dettagli: [POSTGRES.md](POSTGRES.md).

---

## Auth e Web

| Env | Default | UI |
|---|---|---|
| `AUTH_USER` / `AUTH_PASS` | *(vuoto = pubblica)* | **no — solo env** |
| `SECRET_KEY` | *(random ad ogni restart)* | no |
| `SESSION_DAYS` | `7` | no |
| `WEB_PORT` | `8080` | no |

Le credenziali restano fuori dalla UI per evitare lock-out. In produzione setta
`SECRET_KEY` a una stringa lunga random.

---

## Storage locale

| Env | Default |
|---|---|
| `LOG_DIR` | `/data` |
| `COUNTS_FILE` | `$LOG_DIR/counts.json` |
| `EVENTS_FILE` | `$LOG_DIR/events.jsonl` |
| `SETTINGS_FILE` | `$LOG_DIR/settings.json` |

> `settings.json` contiene password in chiaro (RTSP URL, MQTT/DB) — proteggi il
> volume `/data` e non versionarlo.

---

## Restart richiesto

Cambiando questi dalla UI serve `docker compose restart counter`:

- `RTSP_URL`, `RTSP_TRANSPORT`, `CAPTURE_*`
- `MODEL_PATH`, `DETECT_INPUT_SIZE`, `ORT_THREADS`
- `TRACK_MAX_AGE`, `TRACK_MIN_HITS`, `TRACK_IOU`
- `MQTT_*`

Tutto il resto (linea, ROI, direzione, FPS, conf, overlay, webhook, Postgres) è
applicato immediatamente.

---

## API HTTP

Tutti gli endpoint `/api/*` accettano cookie di sessione **o** HTTP Basic Auth.

| Method | Route | Cosa fa |
|---|---|---|
| GET | `/` | dashboard |
| GET | `/settings` | impostazioni |
| GET | `/api/counts` | totali correnti |
| GET | `/api/hourly?day=` | 24 bucket orari |
| GET | `/api/events?day=&from=&to=` | eventi filtrati |
| GET | `/api/days` | giorni con dati |
| GET | `/api/tracks` | persone attualmente tracciate (live) |
| GET | `/api/health` | stato stream + detection (fps, ms, riconnessioni) |
| GET | `/api/snapshot` | ultimo frame annotato (JPEG) |
| GET | `/api/snapshot/diag` | diagnosi sintetica dello stream |
| POST | `/api/settings` | salva configurazione |
| POST | `/api/db/test` · GET `/api/db/sql` | test/Schema Postgres |
| POST | `/api/webhook/test` | invia evento di test |
| POST | `/api/admin/reset-counters` · `reset-day` · `reset-all` | reset |
| GET | `/export.csv?day=` | esporta CSV del giorno |

```bash
curl -u admin:s3gret0 http://host:8080/api/counts
# {"enter": 1247, "exit": 1243, "occupancy": 4}
curl -u admin:s3gret0 http://host:8080/api/health
# {"opened": true, "fps": 12.0, "detect_ms": 41.3, "proc_fps": 8.0, ...}
```
