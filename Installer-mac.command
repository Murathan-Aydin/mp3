#!/usr/bin/env bash
#
# Installateur tout-en-un pour un Mac VIERGE (rien d'installé).
# Double-clique ce fichier : il installe Homebrew, Python, yt-dlp, ffmpeg et deno,
# puis lance l'interface web. Les fois suivantes, il relance simplement l'interface.
#
cd "$(dirname "$0")"

echo "🎵  MP3 Downloader — installation / lancement"
echo "------------------------------------------------"
echo

# --- 1) Homebrew (installe aussi les outils de dev Apple si besoin) ---------
if ! command -v brew >/dev/null 2>&1; then
  echo "→ Installation de Homebrew (peut demander ton mot de passe Mac)..."
  echo "  (une seule fois, ça peut prendre plusieurs minutes)"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
    || { echo "❌ Échec de l'installation de Homebrew."; echo "Appuie sur Entrée pour fermer."; read; exit 1; }
fi

# Charge brew dans cette session (Apple Silicon /opt/homebrew, Intel /usr/local)
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

# --- 2) Les paquets nécessaires --------------------------------------------
echo
echo "→ Vérification des outils (python, yt-dlp, ffmpeg, deno)..."
for pkg in python yt-dlp ffmpeg deno; do
  # nom de commande à tester (python -> python3)
  cmd="$pkg"; [ "$pkg" = "python" ] && cmd="python3"
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "   ✓ $pkg déjà présent"
  else
    echo "   → installation de $pkg..."
    brew install "$pkg" || { echo "❌ Échec sur $pkg."; echo "Appuie sur Entrée pour fermer."; read; exit 1; }
  fi
done

# Recharge le PATH au cas où python vient d'être installé
eval "$(brew shellenv)" 2>/dev/null || true

# Choisit l'interpréteur Python à utiliser
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "❌ Python introuvable après installation."; echo "Appuie sur Entrée pour fermer."; read; exit 1
fi

echo
echo "✅ Tout est prêt."
echo "→ Lancement de l'interface... (garde cette fenêtre ouverte, ferme-la pour arrêter)"
echo

# --- 3) Lance l'interface (elle ouvre le navigateur toute seule) ------------
"$PY" app.py

# Si l'appli s'arrête, laisse la fenêtre lisible
echo
echo "Interface arrêtée. Appuie sur Entrée pour fermer cette fenêtre."
read
