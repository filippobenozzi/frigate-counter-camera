# Configurazione

Due livelli di priorità:

1. **Variabili d'ambiente Docker** — caricate all'avvio, sono i **default**
2. **`/data/settings.json`** — sovrascrive le env, modificabile dalla UI

Salvando dalla pagina **Impostazioni**, `settings.json` viene riscritto. I
parametri di connessione MQTT sono *richiede restart* (la connessione è già
attiva); token, Postgres e webhook sono applicati subito.

---

## MQTT (sorgente eventi dall'ESP)

| Env | Default | UI | Note |
|---|---|---|---|
| `MQTT_HOST` | `mosquitto` | sì (restart) | host del broker (nel compose: il servizio `mosquitto`) |
| `MQTT_PORT` | `1883` | sì (restart) | |
| `MQTT_USER` | *(vuoto)* | sì (restart) | utente del broker (= quello dell'ESP) |
| `MQTT_PASS` | *(vuoto)* | sì (restart) | password del broker |
| `MQTT_TOPIC` | `people_counter/#` | sì (restart) | topic sottoscritto (anche wildcard `+`/`#`) |
| `MQTT_ENTER_TOKENS` | `enter,in,entrata` | sì | parole (CSV) che indicano un ingresso |
| `MQTT_EXIT_TOKENS` | `exit,out,uscita` | sì | parole (CSV) che indicano un'uscita |

**Riconoscimento enter/exit** (in ordine): ultimo segmento del *topic* →
*payload* testo → *payload* JSON (campi `event/direction/type/action/state/dir`).
Vedi [README](README.md#formato-mqtt-accettato). La pagina Impostazioni mostra
messaggi ricevuti e **non riconosciuti** (per tarare i token).

### Il broker Mosquitto (incluso)

Nel `docker-compose` il servizio `mosquitto` crea il file password dalle env
`MQTT_USER`/`MQTT_PASS` e avvia il broker con `allow_anonymous false`. L'ESP si
connette a `<ip-host>:1883` con le stesse credenziali. Config in
[`mosquitto/mosquitto.conf`](mosquitto/mosquitto.conf).

> ⚠️ Le credenziali del broker vanno impostate in **due punti** del compose con
> lo **stesso valore**: nel servizio `mosquitto` (env che generano il file
> password) e nel servizio `counter` (env `MQTT_USER`/`MQTT_PASS` con cui l'app
> si connette). E poi le stesse sull'ESP.

---

## Identificazione

| Env | Default | UI |
|---|---|---|
| `CAMERA_NAME` | `ingresso` | sì — etichetta nei dati / webhook |

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
  "ts": 1716470000.123, "datetime": "2026-06-13 18:42:13",
  "occupancy": 4, "enter_total": 1247, "exit_total": 1243,
  "method": "mqtt", "event_id": "1716470000.123-57",
  "topic": "people_counter/ingresso/enter",
  "reason": "mqtt topic=... payload=enter"
}
```

---

## PostgreSQL (opzionale)

| Env | Default |
|---|---|
| `DB_HOST` / `DB_PORT` | *(vuoto)* / `5432` |
| `DB_NAME` / `DB_USER` / `DB_PASS` | *(vuoto)* |
| `DB_SCHEMA` / `DB_TABLE` | `public` / `counter_events` |
| `DB_SSLMODE` | `prefer` |

Vuoti → solo `events.jsonl`. Compilati → JSON **e** Postgres. Dettagli:
[POSTGRES.md](POSTGRES.md).

---

## Auth e Web

| Env | Default | UI |
|---|---|---|
| `AUTH_USER` / `AUTH_PASS` | *(vuoto = pubblica)* | **no — solo env** |
| `SECRET_KEY` | *(random)* | no |
| `SESSION_DAYS` | `7` | no |
| `WEB_PORT` | `8080` | no |
| `TZ` | `Europe/Rome` | no — fuso per gli orari |

---

## Storage locale

| Env | Default |
|---|---|
| `LOG_DIR` | `/data` |
| `COUNTS_FILE` | `$LOG_DIR/counts.json` |
| `EVENTS_FILE` | `$LOG_DIR/events.jsonl` |
| `SETTINGS_FILE` | `$LOG_DIR/settings.json` |

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
| GET | `/api/health` | stato MQTT (connesso, messaggi, ignorati, ultimo topic) |
| POST | `/api/settings` | salva configurazione |
| POST | `/api/db/test` · GET `/api/db/sql` | test/Schema Postgres |
| POST | `/api/webhook/test` | invia evento di test |
| POST | `/api/admin/reset-counters` · `reset-day` · `reset-all` | reset |
| GET | `/export.csv?day=` | esporta CSV |

```bash
curl -u filippo:pass http://host:8080/api/counts
# {"enter": 1247, "exit": 1243, "occupancy": 4}
curl -u filippo:pass http://host:8080/api/health
# {"connected": true, "topic": "people_counter/#", "messages": 42, "ignored": 0, ...}
```
