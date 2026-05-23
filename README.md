# Frigate Person Counter

Conteggio direzionale di persone per [Frigate NVR](https://frigate.video/).
Consuma gli eventi MQTT `frigate/events`, analizza la traiettoria di ogni
persona rilevata e classifica l'attraversamento come **ingresso** o **uscita**.

- Dashboard web con totali in tempo reale, grafico orario e navigazione tra
  giorni passati
- Pagina di **Impostazioni** unificata con snapshot live della camera per
  disegnare graficamente la linea di attraversamento e la ROI
- Storage su **JSON locale** + **PostgreSQL** opzionale come integrazione esterna
- **Webhook** configurabile, invia un POST JSON ad ogni enter/exit
- Autenticazione opzionale (login form + HTTP Basic per le API)

---

## Quick start (Docker Compose)

```bash
git clone <questo-repo>
cd frigate-counter-camera
cp docker-compose.example.yml docker-compose.yml
# modifica i valori in docker-compose.yml (MQTT_HOST, FRIGATE_URL, CAMERA_NAME, AUTH_*)
docker compose up -d
```

Poi apri **http://localhost:8080** e fai login con le credenziali messe in
`AUTH_USER` / `AUTH_PASS`.

Il primo passo dopo l'avvio è andare in **Impostazioni** e:

1. Cliccare *↻ Carica camere da Frigate* per popolare il dropdown delle camere
2. Trascinare la **linea gialla** sullo snapshot dove c'è la soglia fisica della porta
3. Restringere il **rettangolo azzurro (ROI)** all'area della porta
4. Cliccare **Salva**

I conteggi iniziano immediatamente, senza restart.

---

## Cosa fa esattamente

1. Si connette al broker MQTT del Frigate
2. Si sottoscrive a `frigate/events` e filtra solo gli eventi `label=person`
   della camera scelta
3. Per ogni evento tiene un *track*: lista di punti normalizzati (0..1) che
   rappresentano la posizione della persona nel tempo
4. Quando l'evento Frigate termina (`type=end`), classifica il movimento:
   - **`line_cross`** (default): la traiettoria deve attraversare una linea
     orizzontale, partendo da sopra (con margine) e arrivando sotto (con
     margine), o viceversa. Robusto contro chi staziona davanti alla porta.
   - **`full_motion`**: analisi del movimento totale (`delta_y`, `span_y`,
     `net_ratio`). Più sensibile, può contare falsi positivi.
5. Se è enter o exit: incrementa i contatori, salva l'evento, pubblica i nuovi
   totali su MQTT (`counter/<camera>/enter|exit|occupancy`), opzionalmente
   chiama il webhook.

---

## Struttura del progetto

```
frigate-counter-camera/
├── Dockerfile
├── docker-compose.example.yml
├── requirements.txt
├── main.py                       # entrypoint
├── sql/
│   └── schema.sql                # schema Postgres pre-pronto (vedi POSTGRES.md)
├── app/
│   ├── config.py                 # default da env
│   ├── settings.py               # runtime override (settings.json)
│   ├── motion.py                 # classificatore line_cross + full_motion
│   ├── tracker.py                # stato in-memory dei track attivi
│   ├── mqtt_listener.py          # consumo eventi Frigate
│   ├── storage.py                # JSON + Postgres (orchestrato)
│   ├── webhook.py                # POST async ad ogni enter/exit
│   ├── auth.py                   # login form + HTTP Basic
│   ├── web.py                    # Flask app + routes
│   └── templates/
│       ├── login.html
│       ├── dashboard.html        # totali, grafico, tabella, nav giorni
│       └── settings.html         # canvas interattivo + form + reset
├── README.md
├── CONFIG.md                     # tutti i parametri configurabili
└── POSTGRES.md                   # schema, setup, troubleshooting
```

---

## File generati a runtime in `/data`

- `counts.json` — contatori cumulativi (enter, exit, occupancy)
- `events.jsonl` — log di tutti gli eventi (un evento per riga JSON)
- `settings.json` — override runtime delle env. **Editato dalla UI in Impostazioni.**

Tutti questi file vivono nel volume montato in `/data`. Per migrare l'app su
un altro host basta copiare la cartella.

---

## URL della web app

| Route | Descrizione |
|---|---|
| `/` | dashboard con totali, grafico, tabella eventi, navigazione giorni |
| `/settings` | impostazioni complete (camera, MQTT, Frigate, Postgres, webhook, reset) |
| `/login` · `/logout` | auth |

Tutti gli endpoint `/api/*` accettano sia cookie di sessione che HTTP Basic Auth.
Vedi [CONFIG.md](CONFIG.md) per la lista completa.

---

## Documentazione

- **[CONFIG.md](CONFIG.md)** — tutti i parametri configurabili (env e da UI),
  webhook payload, API reference
- **[POSTGRES.md](POSTGRES.md)** — schema della tabella, setup del database,
  view di riepilogo, troubleshooting

---

## Licenza / contributi

Progetto personale. PR benvenute.
