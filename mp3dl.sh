#!/usr/bin/env bash
#
# mp3dl — Télécharge des musiques YouTube en MP3 (320 kbps) avec pochette + métadonnées.
#
# Lance le script, colle tes liens, appuie sur Entrée puis Ctrl-D.
#   ./mp3dl.sh
#
# Tout est toujours enregistré dans le dossier ./download (à côté du script).
set -euo pipefail

cd "$(dirname "$0")"
DEST="./download"
URLS=()

# Mode interactif : colle tes liens
echo "🎵  Colle tes liens YouTube (un par ligne)."
echo "    Quand tu as fini : appuie sur Entrée puis Ctrl-D."
echo
while IFS= read -r line; do
  line="${line// }"
  [[ -z "$line" || "$line" == \#* ]] && continue
  URLS+=("$line")
done

if [[ ${#URLS[@]} -eq 0 ]]; then
  echo "Aucun lien fourni."
  exit 1
fi

mkdir -p "$DEST"
echo
echo "→ ${#URLS[@]} lien(s) — téléchargement dans : $DEST"
echo

yt-dlp \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 0 \
  --embed-thumbnail \
  --add-metadata \
  --embed-metadata \
  --ignore-errors \
  --continue \
  --no-overwrites \
  --output "$DEST/%(title)s.%(ext)s" \
  "${URLS[@]}"

echo
echo "✅ Terminé. Fichiers dans : $DEST"
