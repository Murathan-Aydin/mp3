FROM python:3.12-slim-bookworm

# deno = runtime JavaScript utilisé par yt-dlp pour résoudre les défis JS de YouTube
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# ffmpeg = nécessaire pour convertir en MP3 et intégrer la pochette
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp installé via pip (facile à mettre à jour en rebuild).
# L'extra [default] inclut yt-dlp-ejs : les scripts que deno exécute pour résoudre
# les défis JS de YouTube (sans eux : « Signature solving failed »).
RUN pip install --no-cache-dir --upgrade "yt-dlp[default]"

# Camoufox (Firefox anti-détection piloté par Playwright) : connexion automatique au
# compte Google (ytlogin.py) pour récupérer les cookies YouTube tout seul
# (GOOGLE_EMAIL / GOOGLE_PASSWORD). Le Firefox standard de Playwright est refusé
# par Google (« navigateur non sécurisé »). gcc/g++ servent seulement à compiler
# une dépendance (indexed-zstd) puis sont retirés.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ libc6-dev libzstd-dev \
    && pip install --no-cache-dir camoufox \
    && playwright install-deps firefox \
    && python3 -m camoufox fetch \
    && rm -rf /root/.cache/camoufox/browsers/*/*/fonts/M \
              /root/.cache/camoufox/browsers/*/*/fonts/W \
              /root/.cache/camoufox/browsers/*/*/fonts/MW \
    && apt-get purge -y gcc g++ libc6-dev libzstd-dev && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /root/.cache/pip

WORKDIR /app
COPY app/app.py app/ytlogin.py ./

ENV HOST=0.0.0.0 \
    PORT=8756 \
    DOWNLOAD_DIR=/app/download \
    COOKIES_FILE=/app/config/cookies.txt

RUN mkdir -p /app/download /app/config
EXPOSE 8756

CMD ["python3", "app.py"]
