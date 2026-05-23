# Configurazione

Tutti i parametri hanno **due livelli di priorità**:

1. **Variabili d'ambiente Docker** — caricate all'avvio, usate come **default**
2. **`/data/settings.json`** — sovrascrive le env, modificabile a runtime dalla UI

Quando salvi dalla pagina **Impostazioni**, il file `settings.json` viene
riscritto e i nuovi valori entrano in vigore subito (eccetto MQTT e auth — vedi
[Restart richiesto](#restart-richiesto) sotto).

---

## Indice

- [Detection (linea, ROI, soglie)](#detection)
- [Camera](#camera)
- [MQTT](#mqtt-broker)
- [Frigate](#frigate)
- [PostgreSQL](#postgresql)
- [Webhook](#webhook)
- [Auth e Web](#auth-e-web)
- [Storage locale](#storage-locale)
- [Restart richiesto](#restart-richiesto)
- [API HTTP](#api-http)

---

## Detection

### Modalità di conteggio

| Env | Default | UI | Note |
|---|---|---|---|
| `COUNT_MODE` | `line_cross` | sì | `line_cross` (raccomandato) o `full_motion` |
| `ENTER_DIRECTION` | `up` | sì | `up` = entrare = dal basso verso l'alto |
| `POINT_MODE` | `bottom` | sì | `bottom` = piedi della persona, `center` = centro del box |

### Linea di attraversamento (modalità `line_cross`)

| Env | Default | Significato |
|---|---|---|
| `LINE_Y` | `0.50` | Posizione verticale 0..1 della linea (0=alto, 1=basso) |
| `LINE_MARGIN` | `0.08` | "Zona morta" sopra/sotto la linea. Chi non la supera non conta |

**Come funziona**: per essere contato, un track deve avere almeno un punto
sopra `LINE_Y - LINE_MARGIN`, almeno uno sotto `LINE_Y + LINE_MARGIN`, e
*primo* e *ultimo* punto su lati opposti. Chi sta avanti/indietro nella zona
morta non viene mai contato.

### ROI (Region Of Interest)

| Env | Default | Significato |
|---|---|---|
| `MOTION_X1` | `0.20` | Bordo sinistro della zona attiva |
| `MOTION_X2` | `0.92` | Bordo destro |
| `MOTION_Y1` | `0.05` | Bordo alto |
| `MOTION_Y2` | `0.98` | Bordo basso |

Tutti normalizzati 0..1. Punti del track fuori dal rettangolo vengono ignorati
prima della classificazione. Usa la ROI per escludere zone irrilevanti (sfondo,
finestre, marciapiede inquadrato di lato).

### Soglie movimento (modalità `full_motion`)

| Env | Default | Significato |
|---|---|---|
| `MOTION_MIN_POINTS` | `4` | Punti minimi del track per provare a classificare |
| `MOTION_MIN_DELTA_Y` | `0.16` | Differenza Y minima tra inizio e fine |
| `MOTION_MIN_SPAN_Y` | `0.20` | Escursione Y minima del track |
| `MOTION_MIN_NET_RATIO` | `0.45` | Rapporto |delta|/span minimo (filtra avanti/indietro) |

### Tracking

| Env | Default | Significato |
|---|---|---|
| `JITTER_DISTANCE` | `0.015` | Distanza minima tra punti consecutivi (filtra micro-mov.) |
| `TRACK_TTL` | `30` | Secondi dopo cui un track inattivo viene scartato |
| `TRACK_POINTS_MAX` | `120` | Numero massimo di punti memorizzati per track |

---

## Camera

| Env | Default | UI |
|---|---|---|
| `CAMERA_NAME` | `ingresso` | sì (con dropdown da Frigate) |
| `FRAME_WIDTH` | `1280` | sì |
| `FRAME_HEIGHT` | `720` | sì |
| `REQUIRED_ZONE` | *(vuoto)* | sì — se settato, considera solo eventi che attraversano questa zona Frigate |

> Il nome camera deve **coincidere esattamente** col nome in `frigate.yml`
> (case-sensitive). Il bottone *↻ Carica camere da Frigate* nella UI popola un
> dropdown con la lista delle camere effettivamente configurate.

---

## MQTT broker

| Env | Default | UI |
|---|---|---|
| `MQTT_HOST` | `127.0.0.1` | sì (richiede restart) |
| `MQTT_PORT` | `1883` | sì (richiede restart) |
| `MQTT_USER` | *(vuoto)* | sì (richiede restart) |
| `MQTT_PASS` | *(vuoto)* | sì (richiede restart) |

**Topic pubblicati dal counter** (retained):

- `counter/<camera>/enter` — contatore totale ingressi
- `counter/<camera>/exit` — contatore totale uscite
- `counter/<camera>/occupancy` — presenti = enter − exit

---

## Frigate

| Env | Default | UI |
|---|---|---|
| `FRIGATE_URL` | *(vuoto)* | sì |
| `SNAPSHOT_REFRESH_SEC` | `3` | sì |

Necessario solo per lo **snapshot live** della pagina Impostazioni
(`GET <FRIGATE_URL>/api/<camera>/latest.jpg`). Senza, tutto il resto funziona
ma non vedi l'immagine della camera.

Se Frigate gira in un altro container del **stesso compose**, usa il nome del
servizio Docker (es. `http://frigate:5000`).

---

## PostgreSQL

| Env | Default | UI |
|---|---|---|
| `DB_HOST` | *(vuoto)* | sì |
| `DB_PORT` | `5432` | sì |
| `DB_NAME` | *(vuoto)* | sì |
| `DB_USER` | *(vuoto)* | sì |
| `DB_PASS` | *(vuoto)* | sì |
| `DB_SCHEMA` | `public` | sì |
| `DB_TABLE` | `counter_events` | sì |
| `DB_SSLMODE` | `prefer` | sì |

> **Tutti vuoti** → l'app usa solo lo storage JSON locale (`events.jsonl`).
> **Compilati** → ogni evento viene scritto sia su JSON sia su Postgres.

Lo store si **riconnette in caldo** appena salvi nuovi valori DB_*: non serve
restartare il container. Usa il bottone *↻ Testa connessione* nella UI per
verificare prima di salvare; *▤ Mostra SQL* per copiare lo schema della
tabella e crearla a mano. Dettagli completi: [POSTGRES.md](POSTGRES.md).

---

## Webhook

| Env | Default | UI |
|---|---|---|
| `WEBHOOK_ENABLED` | `0` | sì |
| `WEBHOOK_URL` | *(vuoto)* | sì |
| `WEBHOOK_HEADERS` | *(vuoto)* | sì — JSON string es. `{"Authorization":"Bearer xxx"}` |
| `WEBHOOK_TIMEOUT` | `4` | sì |
| `WEBHOOK_RETRY` | `1` | sì — retry per errori 5xx / network |

### Payload inviato

Ad ogni **enter** o **exit** il counter invia `POST` con questo JSON:

```json
{
  "event":       "enter",
  "camera":      "ingresso",
  "ts":          1716470000.123,
  "datetime":    "2026-05-23 18:42:13",
  "occupancy":   4,
  "enter_total": 1247,
  "exit_total":  1243,
  "method":      "line_cross",
  "event_id":    "1716...-some-id",
  "start":       {"x": 0.45, "y": 0.10},
  "end":         {"x": 0.43, "y": 0.88},
  "reason":      "line_cross movement=down first_y=0.12 last_y=0.86 ..."
}
```

L'invio è **fire-and-forget** in un worker thread separato: anche se il
webhook è lento o down, il contatore non si blocca. Errori loggati su stdout
del container.

**Test rapido** con un servizio gratuito tipo
[`webhook.site`](https://webhook.site): copia l'URL temporaneo,
mettilo in `WEBHOOK_URL`, abilita, salva e clicca *↻ Invia evento di test*.

### Esempi di consumer

- **Home Assistant**: webhook trigger automatico → notifica push quando
  `occupancy > 10`
- **Node-RED**: HTTP-in node → switch su `event` → invio Slack
- **n8n**: trigger webhook → split sul tipo → side-effect a piacere

---

## Auth e Web

| Env | Default | UI |
|---|---|---|
| `AUTH_USER` | *(vuoto = pubblica)* | **no — solo env** |
| `AUTH_PASS` | *(vuoto)* | **no — solo env** |
| `SECRET_KEY` | *(random ad ogni restart)* | no |
| `SESSION_DAYS` | `7` | no |
| `WEB_PORT` | `8080` | no |

Auth user/pass restano deliberatamente fuori dalla UI: una password sbagliata
salvata dalla UI farebbe lock-out totale. Per cambiarle, modifica il
`docker-compose.yml` e fai restart.

> **Importante**: setta `SECRET_KEY` a una stringa lunga random in produzione,
> altrimenti tutti i token di sessione vengono invalidati ad ogni restart.

---

## Storage locale

| Env | Default | Note |
|---|---|---|
| `LOG_DIR` | `/data` | directory base dei file di storage |
| `COUNTS_FILE` | `$LOG_DIR/counts.json` | contatori cumulativi |
| `EVENTS_FILE` | `$LOG_DIR/events.jsonl` | log eventi (1 evento per riga) |
| `SETTINGS_FILE` | `$LOG_DIR/settings.json` | override runtime |

Monta `/data` come volume Docker. Il singolo file più importante è
`settings.json`: contiene **tutto** quello che hai configurato dalla UI ed è
sufficiente per riprodurre la stessa configurazione su un altro host.

Esempio di `settings.json`:

```json
{
  "CAMERA": "ingresso",
  "COUNT_MODE": "line_cross",
  "ENTER_DIRECTION": "up",
  "POINT_MODE": "bottom",
  "LINE_Y": 0.55,
  "LINE_MARGIN": 0.10,
  "MOTION_X1": 0.25,
  "MOTION_X2": 0.85,
  "MOTION_Y1": 0.10,
  "MOTION_Y2": 0.95,
  "MQTT_HOST": "192.168.1.10",
  "MQTT_PORT": 1883,
  "FRIGATE_URL": "http://192.168.1.10:5000",
  "DB_HOST": "postgres",
  "DB_NAME": "frigate_counter",
  "DB_USER": "counter",
  "DB_PASS": "...",
  "WEBHOOK_ENABLED": true,
  "WEBHOOK_URL": "https://example.com/hook"
}
```

> ⚠️ Il file contiene password in chiaro (MQTT_PASS, DB_PASS, ecc.) — proteggilo
> con permessi appropriati e non versionarlo.

---

## Restart richiesto

Cambiare questi parametri dalla UI **richiede restart del container** per
diventare effettivo (la connessione MQTT è già attiva e non viene riaperta):

- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`

Quando salvi, l'UI mostra un banner di avviso. Esegui:

```bash
docker compose restart counter
```

Tutti gli altri parametri (linea, ROI, soglie, camera, Frigate URL, Postgres,
webhook) sono **applicati immediatamente**.

---

## API HTTP

Tutti gli endpoint sotto `/api/*` accettano sia cookie di sessione che HTTP
Basic Auth con le credenziali in `AUTH_USER` / `AUTH_PASS`.

| Method | Route | Cosa fa |
|---|---|---|
| GET  | `/` | dashboard |
| GET  | `/settings` | pagina impostazioni |
| GET  | `/login`, `/logout` | auth |
| GET  | `/export.csv?day=YYYY-MM-DD` | CSV degli eventi di un giorno |
| GET  | `/api/counts` | totali cumulativi correnti |
| GET  | `/api/hourly?day=YYYY-MM-DD` | 24 bucket orari del giorno |
| GET  | `/api/events?day=YYYY-MM-DD&from=H&to=H` | eventi filtrati |
| GET  | `/api/days` | giorni con dati |
| GET  | `/api/tracks` | track attivi in memoria (debug) |
| POST | `/api/admin/reset-counters` | azzera cumulativi (storico intatto) |
| POST | `/api/admin/reset-day` `day=YYYY-MM-DD` | cancella eventi del giorno + aggiusta cumulativi |
| POST | `/api/admin/reset-all` | wipe totale storico + cumulativi |
| GET  | `/api/settings` | settings correnti + schema |
| POST | `/api/settings` | salva nuovi valori |
| POST | `/api/db/test` | testa connessione Postgres senza salvare |
| GET  | `/api/db/sql` | restituisce lo SQL `CREATE TABLE` |
| POST | `/api/webhook/test` | invia un evento di test al webhook configurato |
| GET  | `/api/frigate/cameras` | lista camere lette da Frigate |
| GET  | `/api/snapshot` | proxy del latest.jpg di Frigate |
| GET  | `/api/snapshot/diag` | diagnostica connessione a Frigate |

Esempio:

```bash
curl -u admin:s3gret0 http://host:8080/api/counts
# {"enter": 1247, "exit": 1243, "occupancy": 4}
```
