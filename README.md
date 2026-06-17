# Person Counter — MQTT (ESP people counter)

Conteggio persone alimentato da **eventi MQTT**: un dispositivo **ESP** (people
counter) pubblica gli eventi `enter`/`exit` su un broker MQTT, e questa app li
consuma, tiene i contatori e li mostra in una dashboard web con storico.

Lo stack include un **broker Mosquitto** (con autenticazione) già pronto: l'ESP
pubblica lì, l'app si sottoscrive.

- Niente più telecamere/AI: sorgente = **MQTT**, leggerissimo
- Dashboard: totali live, grafico orario, navigazione tra i giorni
- Storage **JSON locale** + **PostgreSQL** opzionale
- **Webhook** (POST ad ogni enter/exit) opzionale
- Auth opzionale (login form + HTTP Basic per le API)
- **Parser tollerante**: riconosce enter/exit dal topic o dal payload (testo o
  JSON), con token configurabili → funziona con firmware ESP diversi

---

## Architettura

```
  ESP people counter  ──MQTT──►  Mosquitto (broker, auth)  ──►  app (subscriber)
   pubblica enter/exit            incluso nello stack              │
                                                                   ▼
                                                    contatori (enter/exit/presenti)
                                                                   │
                                   ┌───────────────┬───────────────┼──────────────┐
                                   ▼               ▼               ▼              ▼
                              counts.json     events.jsonl     Postgres        webhook
                                                                              dashboard
```

---

## Quick start

```bash
cp docker-compose.example.yml docker-compose.yml
# modifica le credenziali: MQTT_USER/MQTT_PASS (broker), AUTH_USER/AUTH_PASS (dashboard)
docker compose up -d --build
```

- Dashboard: **http://localhost:8080** (login con `AUTH_USER`/`AUTH_PASS`)
- Broker MQTT per l'ESP: **`<ip-host>:1883`**, utente/password = `MQTT_USER`/`MQTT_PASS`

Configura l'ESP per pubblicare su un topic sotto quello sottoscritto (default
`people_counter/#`), es. `people_counter/ingresso/enter`.

---

## Formato MQTT accettato

L'app per ogni messaggio decide **enter** o **exit** guardando, in ordine:

1. **l'ultimo segmento del topic** — es. `people_counter/ingresso/enter` → enter
2. **il payload come testo** — es. `enter`, `in`, `uscita`
3. **il payload JSON** — nei campi `event`, `direction`, `type`, `action`,
   `state`, `dir` — es. `{"event":"exit"}`, `{"direction":"in"}`

### Dispositivo a raggio singolo (conteggio passaggi)

L'ESP people counter usa **un solo sensore a ultrasuoni**: rileva un
**passaggio** (qualcuno attraversa il raggio) ma **non la direzione**. Pubblica
`peoplecounter/event` = `pass` ad ogni passaggio.

Poiché una persona genera ~2 passaggi (entra + esce), si **stima dividendo per 2**.
Il parametro `PASSAGE_MODE` decide come mappare i passaggi:

| `PASSAGE_MODE` | Comportamento |
|---|---|
| `alternate` *(default)* | alterna entrata/uscita → **entrate ≈ uscite ≈ passaggi/2** |
| `enter` | ogni passaggio = entrata (se il varco è solo d'ingresso) |
| `exit` | ogni passaggio = uscita |

I messaggi di telemetria del firmware (`count`, `distance`, `availability`)
vengono ignorati automaticamente.

### Token (per dispositivi direzionali)

Se un domani usi un dispositivo che distingue la direzione, i token CSV mappano
le parole su enter/exit/pass:

| Parametro | Default |
|---|---|
| `MQTT_ENTER_TOKENS` | `enter,in,entrata` |
| `MQTT_EXIT_TOKENS` | `exit,out,uscita` |
| `MQTT_PASS_TOKENS` | `pass,passage,passaggio` |

Se l'ESP usa parole diverse (es. `IN`/`OUT`, `1`/`0`), aggiungile ai token
dalle Impostazioni — niente modifiche al codice. La pagina Impostazioni mostra
quanti messaggi sono arrivati e quanti **non riconosciuti** (per tarare i token).

Esempi che funzionano subito:
```
topic: people_counter/ingresso/enter   payload: (qualsiasi)
topic: people_counter/varco            payload: out
topic: esp/people                      payload: {"direction":"in"}   (se MQTT_TOPIC li copre)
```

---

## Struttura del progetto

```
.
├── Dockerfile                    # immagine leggera (flask + paho + psycopg2)
├── docker-compose.example.yml    # mosquitto + counter + postgres
├── mosquitto/mosquitto.conf      # config broker (auth)
├── requirements.txt
├── main.py                       # entrypoint
├── sql/schema.sql                # schema Postgres
├── app/
│   ├── config.py                 # default da env
│   ├── settings.py               # override runtime (settings.json) + UI
│   ├── mqtt_in.py                # subscriber MQTT + parser enter/exit
│   ├── storage.py                # JSON + Postgres
│   ├── webhook.py                # POST async ad ogni enter/exit
│   ├── auth.py                   # login form + HTTP Basic
│   ├── web.py                    # Flask app + API
│   └── templates/                # login, dashboard, settings
├── README.md · CONFIG.md · POSTGRES.md
```

## File a runtime in `/data`
- `counts.json` — contatori cumulativi
- `events.jsonl` — log eventi
- `settings.json` — configurazione modificata da UI

> ⚠️ Se aggiorni da una versione precedente (a telecamera), **cancella il vecchio
> `data/settings.json`**: conteneva parametri di un'altra architettura che
> sovrascriverebbero la config MQTT.

---

## Documentazione
- **[CONFIG.md](CONFIG.md)** — parametri (env + UI), payload webhook, API
- **[POSTGRES.md](POSTGRES.md)** — schema tabella, setup DB, query
