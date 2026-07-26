# 🎵 MP3 Downloader

Télécharge des musiques YouTube en MP3 (320 kbps, pochette + métadonnées) via une
petite interface web locale. Colle un ou plusieurs liens (playlist ou musique seule),
clique sur **Installer**, et récupère un **ZIP** de tes morceaux.

## Contenu du dossier

```
run.command   ← le seul fichier à lancer (installe tout puis ouvre l'interface)
download/     ← tes MP3 téléchargés
app/          ← le code (tu n'as pas besoin d'y toucher)
```

---

## Installation sur Mac (même un Mac tout neuf)

### Méthode recommandée — `git clone` (le double-clic marchera direct)

```bash
git clone https://github.com/Murathan-Aydin/mp3.git
cd mp3
./run.command
```

> La première fois, `git` peut proposer d'installer les « outils de développement »
> Apple : accepte, c'est normal.

`run.command` installe tout seul ce qu'il faut la première fois (**Homebrew, Python,
yt-dlp, ffmpeg, deno**) puis ouvre l'interface. Les fois suivantes, il lance direct.

### Méthode ZIP (téléchargement depuis GitHub)

1. Sur GitHub : bouton vert **Code → Download ZIP**, puis décompresse.
2. Ouvre le **Terminal**, va dans le dossier, et rends le script exécutable :
   ```bash
   cd ~/Downloads/mp3-main      # adapte le chemin
   chmod +x run.command
   ./run.command
   ```

> ⚠️ **Pourquoi le double-clic ne marche pas après un ZIP ?**
> Le téléchargement ZIP de GitHub perd le « bit exécutable ». La commande
> `chmod +x run.command` le remet — après ça, le double-clic fonctionne.

> ⚠️ **macOS bloque « développeur non identifié » ?**
> Clic droit sur `run.command` → **Ouvrir** → **Ouvrir**. Une seule fois.

---

## Utilisation

- **Interface web** : double-clic sur **`run.command`** → la page s'ouvre dans le
  navigateur. Colle tes liens → **Installer** → le ZIP se télécharge.
- **En ligne de commande** (optionnel) : `app/mp3dl.sh`, colle les liens, Entrée, Ctrl-D.

Les MP3 arrivent dans le dossier **`download/`**.

---

## Déploiement serveur (Docker / Coolify)

```bash
cd app
docker compose up -d --build
```

Sur un serveur, YouTube demande souvent une authentification (« confirm you're not a
bot »). Ajoute un fichier **cookies YouTube** : sur Coolify, crée un *File Mount* vers
`/app/cookies.txt` avec le contenu exporté depuis ton navigateur
(extension « Get cookies.txt LOCALLY »).

---

## Mise à jour de yt-dlp

YouTube change souvent ; si les téléchargements échouent, mets yt-dlp à jour :

```bash
brew upgrade yt-dlp     # installation locale Mac
```

---

## ⚠️ Usage

À réserver à un usage **personnel/privé**. Ne redistribue pas de contenu protégé.
