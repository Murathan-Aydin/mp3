#!/usr/bin/env bash
#
# Installateur tout-en-un pour Mac.
# Double-clique ce fichier : il installe ce qu'il faut puis lance l'interface web.
#
set -e
cd "$(dirname "$0")"

echo "🎵  Installation du MP3 Downloader..."
echo

# 1) Homebrew (gestionnaire de paquets Mac)
if ! command -v brew >/dev/null 2>&1; then
  echo "→ Installation de Homebrew (peut demander ton mot de passe Mac)..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Ajoute brew au PATH pour cette session (Apple Silicon + Intel)
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi

# 2) Les outils nécessaires
echo "→ Vérification de yt-dlp, ffmpeg et deno..."
for pkg in yt-dlp ffmpeg deno; do
  if ! command -v "$pkg" >/dev/null 2>&1; then
    echo "   installation de $pkg..."
    brew install "$pkg"
  fi
done

echo
echo "✅ Tout est prêt. Lancement de l'interface..."
echo "   (Garde cette fenêtre ouverte. Ferme-la pour arrêter.)"
echo

# 3) Lance l'interface web (ouvre le navigateur automatiquement)
python3 app.py
