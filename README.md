# Person Counter — RTSP + YOLOv8 (CPU)

Conteggio direzionale di persone **autonomo**: apre direttamente lo stream
**RTSP/RTSPS** della telecamera, rileva le persone con **YOLOv8n** (ONNX
Runtime, solo CPU), le traccia con **SORT** e conta gli attraversamenti di una
linea configurabile. Non richiede Frigate né altri NVR.

- Funziona su **CPU** (mini-PC / NUC x86): detection a FPS ridotto + tracking
- Dashboard web: totali live, grafico orario, navigazione tra i giorni
- Pagina **Impostazioni** con **snapshot live** della camera (box disegnati) per
  tarare graficamente linea e ROI trascinandole
- Storage **JSON locale** + **PostgreSQL** opzionale
- **Webhook** (POST ad ogni enter/exit) e **MQTT output** opzionali
- Auth opzionale (login form + HTTP Basic per le API)

---

## Come funziona

```
 RTSP/RTSPS ──► cattura ──► YOLOv8n (ONNX, CPU) ──► SORT (Kalman+IoU)
   stream      (thread)        detection persona      tracking identità
                                                            │
                                                            ▼
                                              attraversamento linea + ROI
                                                            │
                              ┌─────────────┬───────────────┼───────────────┐
                              ▼             ▼               ▼               ▼
                         counts.json   events.jsonl     Postgres        webhook
                                                                        + MQTT
```

1. Un thread legge lo stream e tiene solo l'ultimo frame (no latenza accumulata)
2. A `DETECT_FPS` fotogrammi/sec il detector trova le persone (box + confidenza)
3. SORT mantiene l'identità di ogni persona tra un frame e l'altro
4. Per ogni persona si segue da che lato della **linea** sta: quando attraversa
   da una zona all'altra (superando il **margine**) dentro la **ROI**, conta
   `enter` o `exit` secondo `ENTER_DIRECTION`
5. L'evento viene salvato (JSON + Postgres), pubblicato su MQTT e inviato al webhook

La macchina a stati per-persona conta **solo gli attraversamenti completi**: chi
staziona davanti alla porta o va avanti/indietro nella zona morta non viene contato.

---

## Quick start (Docker Compose)

```bash
cp docker-compose.example.yml docker-compose.yml
# modifica RTSP_URL (substream consigliato), AUTH_*, e gli altri parametri
docker compose up -d --build       # il build esporta yolov8n.onnx (richiede ~qualche minuto)
```

Apri **http://localhost:8080**, fai login, vai in **Impostazioni → Camera**:

1. Vedi lo snapshot live con i box delle persone rilevate
2. Trascina la **linea gialla** sulla soglia fisica della porta
3. Restringi il **rettangolo azzurro (ROI)** alla zona utile
4. **Salva** — il conteggio parte subito

> Il modello `yolov8n.onnx` viene esportato automaticamente durante il build
> Docker (stage `model-builder`, usa ultralytics+torch SOLO in build). L'immagine
> runtime resta leggera (~400 MB, niente PyTorch). Puoi anche montare un tuo
> `.onnx` in `/models` e puntarlo con `MODEL_PATH`.

---

## Requisiti hardware

Pensato per **CPU x86** (mini-PC / NUC). Indicazioni:

| Hardware | DETECT_FPS consigliato | Note |
|---|---|---|
| NUC / mini-PC i3-i5 | 8–12 | ottimo, 1-2 core per l'inferenza |
| Server multi-core | 10–15 | si può alzare input size |
| Raspberry Pi 4/5 | 3–6 | possibile ma al limite; usa substream piccolo |

Usa **`ORT_THREADS`** per limitare i core dedicati all'inferenza, e
**`DETECT_FPS`** per bilanciare reattività e carico. Conviene puntare il
container a un **substream a bassa risoluzione** (~640px) della telecamera.

---

## Vista dall'alto / fisheye (camere a soffitto)

YOLOv8n-COCO rileva male le persone **viste dall'alto** (testa+spalle scorciate),
specie di notte in IR. Per questi setup usa un **head-detector** (rileva le teste,
ben visibili dall'alto) passandolo come build-arg:

```bash
docker compose build --build-arg \
  MODEL_URL=https://raw.githubusercontent.com/Abcfsa/YOLOv8_head_detector/main/nano.pt
docker compose up -d
```

- `nano.pt` (6 MB, veloce) o `medium.pt` (52 MB, più accurato) — 1 classe "head"
- Imposta `POINT_MODE=center` (si traccia il centro della testa)
- Il modello a 1 classe è gestito automaticamente (`PERSON_CLASS_ID=0`)

> Modello di [Abcfsa/YOLOv8_head_detector](https://github.com/Abcfsa/YOLOv8_head_detector)
> (addestrato su SCUT-HEAD). Verifica la licenza per l'uso che ne fai.

## Struttura del progetto

```
.
├── Dockerfile                    # multi-stage: esporta onnx + runtime leggero
├── docker-compose.example.yml
├── requirements.txt              # opencv-headless, onnxruntime, numpy, flask, psycopg2, paho
├── main.py                       # entrypoint
├── sql/schema.sql                # schema Postgres (vedi POSTGRES.md)
├── app/
│   ├── config.py                 # default da env
│   ├── settings.py               # override runtime (settings.json) + UI
│   ├── capture.py                # cattura RTSP con riconnessione
│   ├── detector.py               # YOLOv8n ONNX (CPU)
│   ├── sort.py                   # tracker SORT (Kalman + IoU)
│   ├── counting.py               # macchina a stati attraversamento linea
│   ├── pipeline.py               # orchestratore cattura→detect→track→conteggio
│   ├── storage.py                # JSON + Postgres
│   ├── webhook.py                # POST async ad ogni enter/exit
│   ├── mqtt_out.py               # pubblicazione MQTT opzionale
│   ├── auth.py                   # login form + HTTP Basic
│   ├── web.py                    # Flask app + API
│   └── templates/                # login, dashboard, settings
├── README.md  ·  CONFIG.md  ·  POSTGRES.md
```

## File a runtime in `/data`

- `counts.json` — contatori cumulativi
- `events.jsonl` — log eventi (1 per riga)
- `settings.json` — **tutta** la configurazione modificata da UI (per migrare:
  copia la cartella `/data`)

---

## Documentazione

- **[CONFIG.md](CONFIG.md)** — tutti i parametri (env + UI), payload webhook, API
- **[POSTGRES.md](POSTGRES.md)** — schema tabella, setup DB, query, troubleshooting
