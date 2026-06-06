# =====================================================================
#  Stage 1 — esporta yolov8n.onnx (usa ultralytics+torch SOLO in build)
# =====================================================================
FROM python:3.12-slim AS model-builder

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# 1) torch/torchvision CPU pinnati (esportatore ONNX legacy, niente CUDA/onnxscript)
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.4.1 torchvision==0.19.1

# 2) ultralytics + onnx pinnato: onnx 1.16.2 produce IR version 10,
#    compatibile con onnxruntime 1.19.x del runtime (IR 13 non sarebbe caricabile)
RUN pip install --no-cache-dir \
        ultralytics==8.3.0 onnx==1.16.2

WORKDIR /export
# Modello scelto a build-time:
#  - default: yolov8n COCO (rileva 'person', adatto a vista frontale/laterale)
#  - vista dall'alto/fisheye: usa un HEAD-detector passando MODEL_URL (1 classe 'head'),
#    molto meglio per le teste viste dall'alto. Esempio:
#      --build-arg MODEL_URL=https://raw.githubusercontent.com/Abcfsa/YOLOv8_head_detector/main/nano.pt
#  - più accuratezza COCO: --build-arg YOLO_MODEL=yolov8s.pt
ARG YOLO_MODEL=yolov8n.pt
ARG MODEL_URL=""
# dynamic=True => input ridimensionabile (DETECT_INPUT_SIZE 416/480/640...)
RUN if [ -n "$MODEL_URL" ]; then \
        echo "Scarico modello custom: $MODEL_URL" && \
        python -c "import urllib.request; urllib.request.urlretrieve('${MODEL_URL}', 'custom.pt')" && \
        python -c "from ultralytics import YOLO; YOLO('custom.pt').export(format='onnx', opset=12, imgsz=640, simplify=False, dynamic=True)"; \
    else \
        python -c "from ultralytics import YOLO; YOLO('${YOLO_MODEL}').export(format='onnx', opset=12, imgsz=640, simplify=False, dynamic=True)"; \
    fi \
 && python -c "import glob, shutil; shutil.move(sorted(glob.glob('*.onnx'))[0], 'model.onnx')"


# =====================================================================
#  Stage 2 — runtime leggero (no torch)
# =====================================================================
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 libglib2.0-0 libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# modello esportato nello stage precedente (nome fisso model.onnx)
COPY --from=model-builder /export/model.onnx /models/model.onnx

COPY main.py .
COPY app ./app

EXPOSE 8080
# Solo /data è un volume. /models NON deve esserlo: il modello è nel layer
# dell'immagine, altrimenti un volume anonimo stantio lo sovrascriverebbe.
VOLUME ["/data"]

CMD ["python", "-u", "main.py"]
