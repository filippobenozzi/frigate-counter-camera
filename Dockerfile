FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# fuso orario di default (sovrascrivibile con la env TZ nel compose)
ENV TZ=Europe/Rome

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY app ./app

EXPOSE 8080
VOLUME ["/data"]

CMD ["python", "-u", "main.py"]
