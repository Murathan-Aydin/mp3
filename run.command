#!/usr/bin/env bash
#
# Lance l'interface web. Autonome : vérifie que tout est installé,
# installe ce qui manque, puis démarre. Utilise-le au quotidien.
# (Si le double-clic ne marche pas après un ZIP : chmod +x *.command une fois.)
#
cd "$(dirname "$0")"

# Charge Homebrew (Apple Silicon puis Intel)
if [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

# Homebrew absent = première install jamais faite -> renvoie vers l'installateur
if ! command -v brew >/dev/null 2>&1; then
  echo "⚠️  Homebrew n'est pas installé."
  echo "   Lance d'abord Installer-mac.command (première mise en place)."
  echo "Appuie sur Entrée pour fermer."
  read
  exit 1
fi

# Vérifie / installe les outils manquants
for pkg in python yt-dlp ffmpeg deno; do
  cmd="$pkg"; [ "$pkg" = "python" ] && cmd="python3"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "→ $pkg manquant, installation..."
    brew install "$pkg" || { echo "❌ Échec sur $pkg."; echo "Appuie sur Entrée."; read; exit 1; }
  fi
done
eval "$(brew shellenv)" 2>/dev/null || true

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "❌ Python introuvable. Lance Installer-mac.command."
  echo "Appuie sur Entrée pour fermer."; read; exit 1
fi

echo "🎵  Lancement de l'interface... (ferme cette fenêtre pour arrêter)"
echo
"$PY" app.py

echo
echo "Interface arrêtée. Appuie sur Entrée pour fermer cette fenêtre."
read
