#!/usr/bin/env bash
#
# Lance l'interface web (sans réinstaller).
# Double-clique ce fichier — ou lance ./run.command dans le Terminal.
# (Si le double-clic ne marche pas après un ZIP : chmod +x *.command une fois.)
#
cd "$(dirname "$0")"

# Charge Homebrew pour trouver python3 (Apple Silicon puis Intel)
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "❌ Python n'est pas installé."
  echo "   Lance d'abord Installer-mac.command (il installe tout)."
  echo "Appuie sur Entrée pour fermer."
  read
  exit 1
fi

echo "🎵  Lancement de l'interface... (ferme cette fenêtre pour arrêter)"
echo
"$PY" app.py

echo
echo "Interface arrêtée. Appuie sur Entrée pour fermer cette fenêtre."
read
