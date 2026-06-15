# PostgreSQL — setup & schema

PostgreSQL è un'**integrazione esterna opzionale**. Quando configurato, ogni
evento (`enter` o `exit`) finisce in una tabella; la dashboard storica e
l'export CSV leggono direttamente da lì invece di scansionare il file JSONL.
Senza Postgres, tutto funziona lo stesso usando solo `events.jsonl`.

---

## Cosa salva e cosa NO

| Salvato in Postgres | Salvato in `counts.json` / `events.jsonl` |
|---|---|
| ✅ Eventi (`enter`/`exit`) con coordinate, timestamp, occupancy | ✅ Eventi (sempre, anche con Postgres attivo) |
| ❌ Contatori cumulativi correnti | ✅ `counts.json` (sempre) |
| ❌ Settings runtime | ✅ `settings.json` (sempre) |

Il counter scrive **sempre** sui file locali come backup; Postgres è un
"sink" aggiuntivo. Questo significa che puoi disattivarlo in qualsiasi
momento e non perdere nulla.

---

## Configurazione dalla UI (raccomandato)

1. Vai su **Impostazioni → PostgreSQL**
2. Compila i campi `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`
   (lascia `DB_SCHEMA=public` e `DB_TABLE=counter_events` se non hai motivo
   di cambiarli)
3. Clicca **↻ Testa connessione**: verifica che l'app si colleghi e ti dice
   se la tabella esiste già
4. Se la tabella manca:
   - se l'utente DB ha permessi `CREATE`, viene creata in automatico al primo
     salvataggio
   - altrimenti, clicca **▤ Mostra SQL**, copia, ed eseguilo come superuser
5. **Salva** → il badge `non connesso` diventa `connesso`

---

## Schema della tabella

```sql
CREATE TABLE counter_events (
    id              BIGSERIAL    PRIMARY KEY,
    event_id        TEXT         NOT NULL,                  -- id evento (ts-track)
    camera          TEXT         NOT NULL,
    ts              TIMESTAMPTZ  NOT NULL,                  -- istante conteggio
    event_type      TEXT         NOT NULL CHECK (event_type IN ('enter','exit')),
    method          TEXT,                                   -- es. 'mqtt'
    start_x         REAL,                                   -- coordinate 0..1
    start_y         REAL,
    end_x           REAL,
    end_y           REAL,
    reason          TEXT,                                   -- diagnostica del classificatore
    enter_total     INTEGER      NOT NULL DEFAULT 0,        -- snapshot DOPO l'evento
    exit_total      INTEGER      NOT NULL DEFAULT 0,
    occupancy       INTEGER      NOT NULL DEFAULT 0,        -- = enter_total - exit_total
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (event_id, event_type)                           -- anti-duplicazione idempotente
);

CREATE INDEX idx_counter_events_camera_ts ON counter_events (camera, ts DESC);
CREATE INDEX idx_counter_events_ts        ON counter_events (ts DESC);
CREATE INDEX idx_counter_events_type      ON counter_events (event_type);
```

L'`UNIQUE (event_id, event_type)` impedisce duplicati se l'app reinvia per
sbaglio lo stesso evento (riavvio, riconnessione MQTT, retry).

---

## View di riepilogo

L'app crea anche due view utili per dashboard esterne (Grafana, Metabase):

### `counter_daily_summary`

```sql
SELECT camera, day, enter_count, exit_count, peak_occupancy
FROM counter_daily_summary
WHERE day >= CURRENT_DATE - INTERVAL '30 days';
```

### `counter_hourly_summary`

```sql
SELECT camera, hour, enter_count, exit_count
FROM counter_hourly_summary
WHERE hour >= NOW() - INTERVAL '24 hours';
```

---

## Setup standalone con `docker-compose`

`docker-compose.example.yml` include già un servizio `postgres` pronto:

```yaml
postgres:
  image: postgres:16-alpine
  restart: unless-stopped
  environment:
    POSTGRES_DB: person_counter
    POSTGRES_USER: counter
    POSTGRES_PASSWORD: counter-pass
  volumes:
    - ./pgdata:/var/lib/postgresql/data
    - ./sql/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro
```

Il mount di `sql/schema.sql` su `/docker-entrypoint-initdb.d/` fa eseguire lo
schema automaticamente la **prima** volta che Postgres parte (DB vuoto).

---

## Setup su Postgres esistente (es. il tuo Postgres di casa)

1. Crea database e utente con permessi minimi:

   ```sql
   CREATE DATABASE person_counter;
   CREATE USER counter WITH PASSWORD 'cambia-questa-password';
   GRANT CONNECT ON DATABASE person_counter TO counter;
   \c person_counter
   GRANT USAGE, CREATE ON SCHEMA public TO counter;
   ```

2. (Opzionale) Crea la tabella tu stesso eseguendo lo schema:

   ```bash
   psql -h <host> -U counter -d person_counter -f sql/schema.sql
   ```

   Oppure dimentica questo passo e lascia che l'app la crei al primo connect
   (richiede però `CREATE` sullo schema).

3. Compila la sezione PostgreSQL nelle Impostazioni e clicca **Testa connessione**.

---

## Query utili

### Contatori del giorno corrente

```sql
SELECT
  COUNT(*) FILTER (WHERE event_type='enter') AS enter,
  COUNT(*) FILTER (WHERE event_type='exit')  AS exit,
  MAX(occupancy)                              AS peak
FROM counter_events
WHERE camera = 'ingresso'
  AND ts >= CURRENT_DATE;
```

### Ora di punta nell'ultima settimana

```sql
SELECT
  EXTRACT(hour FROM ts) AS hour,
  COUNT(*) FILTER (WHERE event_type='enter') AS enter,
  COUNT(*) FILTER (WHERE event_type='exit')  AS exit
FROM counter_events
WHERE camera = 'ingresso'
  AND ts >= NOW() - INTERVAL '7 days'
GROUP BY hour
ORDER BY hour;
```

### Cancella eventi di un giorno

(Stesso effetto del bottone **Reset → giorno** nella UI.)

```sql
DELETE FROM counter_events
WHERE camera = 'ingresso'
  AND ts >= '2026-05-22'::date
  AND ts <  '2026-05-23'::date;
```

> Attenzione: cancellare a mano in Postgres **non** aggiorna i contatori
> cumulativi salvati in `counts.json`. Per restare consistente usa la UI.

---

## Troubleshooting

| Sintomo | Causa probabile | Fix |
|---|---|---|
| Badge `non connesso` | `DB_HOST` errato o irraggiungibile dal container counter | Verifica DNS / network Docker. Per servizi compose usa il nome servizio (es. `postgres`) non `localhost`. |
| `psycopg2.OperationalError: FATAL: password authentication failed` | Password sbagliata | Reinserisci `DB_PASS` (campo masked: lascia `***` per non cambiare) |
| `relation "..." does not exist` ai primi insert | Tabella non creata e utente senza `CREATE` | Esegui a mano `sql/schema.sql` con un utente che ha permessi |
| `duplicate key value violates unique constraint` | l'app ha rinviato lo stesso evento | Innocuo — il `ON CONFLICT DO NOTHING` lo gestisce, il messaggio non dovrebbe nemmeno comparire |
| Storico Postgres "in ritardo" rispetto a `counts.json` | Postgres era irraggiungibile, eventi solo su JSON | Riallinea esportando da JSONL e reimportando con uno script ad hoc (i due storage divergono solo in scenari di downtime DB) |

---

## Migrare dati dal JSONL a un Postgres nuovo

Se hai accumulato eventi solo nel file e poi attivi Postgres, lo storico
precedente **resta solo nel JSONL**. Per copiarlo in tabella:

```bash
docker exec -i person-counter-db \
  psql -U counter -d person_counter <<'SQL'
\copy counter_events (event_id, camera, ts, event_type, method,
                      start_x, start_y, end_x, end_y, reason,
                      enter_total, exit_total, occupancy)
FROM PROGRAM 'jq -r ''[
  .id, .camera, .datetime, .type, .method,
  .start.x, .start.y, .end.x, .end.y, .reason,
  .counts_after.enter, .counts_after.exit, .counts_after.occupancy
] | @csv'' /path/to/events.jsonl'
WITH (FORMAT csv);
SQL
```

(Adatta i path. Richiede `jq` installato.)
