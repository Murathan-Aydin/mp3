#!/usr/bin/env bash
#
# LE SEUL FICHIER À LANCER.
# Double-clique-le (ou ./run.command dans le Terminal).
# Il installe tout ce qu'il faut la première fois (Homebrew, Python, yt-dlp,
# ffmpeg, deno), puis ouvre l'interface web. Les MP3 vont dans le dossier download.
#
# (Si le double-clic ne marche pas après un ZIP : chmod +x run.command une fois.)
#
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "🎵  MP3 Downloader"
echo "-------------------"
echo

# --- 1) Homebrew ------------------------------------------------------------
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "→ Première mise en place : installation de Homebrew"
  echo "  (peut demander ton mot de passe Mac, ça prend quelques minutes)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || { echo "❌ Échec de l'installation de Homebrew."; echo "Appuie sur Entrée."; read; exit 1; }
  if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
fi

# --- 2) Outils nécessaires --------------------------------------------------
for pkg in python yt-dlp ffmpeg deno; do
  cmd="$pkg"; [ "$pkg" = "python" ] && cmd="python3"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "→ Installation de $pkg..."
    brew install "$pkg" || { echo "❌ Échec sur $pkg."; echo "Appuie sur Entrée."; read; exit 1; }
  fi
done
eval "$(brew shellenv)" 2>/dev/null || true

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "❌ Python introuvable."; echo "Appuie sur Entrée pour fermer."; read; exit 1
fi

# --- 3) Lancement -----------------------------------------------------------
echo
echo "✅ Prêt. Lancement de l'interface... (ferme cette fenêtre pour arrêter)"
echo

# Les MP3 vont dans ./download (à la racine, à côté de ce script)
export DOWNLOAD_DIR="$ROOT/download"
"$PY" app/app.py

echo
echo "Interface arrêtée. Appuie sur Entrée pour fermer cette fenêtre."
read
