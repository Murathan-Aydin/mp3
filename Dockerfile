FROM python:3.12-slim

# deno = runtime JavaScript utilisé par yt-dlp pour résoudre les défis JS de YouTube
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# ffmpeg = nécessaire pour convertir en MP3 et intégrer la pochette
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp installé via pip (facile à mettre à jour en rebuild)
RUN pip install --no-cache-dir --upgrade yt-dlp

WORKDIR /app
COPY app/app.py .

ENV HOST=0.0.0.0 \
    PORT=8756 \
    DOWNLOAD_DIR=/app/download \
    COOKIES_FILE=/app/config/cookies.txt

RUN mkdir -p /app/download /app/config
EXPOSE 8756

CMD ["python3", "app.py"]
