FROM python:3.12-slim

# ffmpeg = nécessaire pour convertir en MP3 et intégrer la pochette
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp installé via pip (facile à mettre à jour en rebuild)
RUN pip install --no-cache-dir --upgrade yt-dlp

WORKDIR /app
COPY app.py .

ENV HOST=0.0.0.0 \
    PORT=8756 \
    DOWNLOAD_DIR=/app/download

RUN mkdir -p /app/download
EXPOSE 8756

CMD ["python3", "app.py"]
