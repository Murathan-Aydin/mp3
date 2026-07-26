# 🎵 MP3 Downloader

Télécharge des musiques YouTube en MP3 (320 kbps, pochette + métadonnées) via une
petite interface web locale. Colle un ou plusieurs liens (playlist ou musique seule),
clique sur **Installer**, et récupère un **ZIP** de tes morceaux.

---

## Installation sur Mac (même un Mac tout neuf)

### Méthode recommandée — `git clone` (le double-clic marchera direct)

```bash
git clone https://github.com/Murathan-Aydin/mp3.git
cd mp3
./Installer-mac.command
```

> La première fois, `git` peut proposer d'installer les « outils de développement »
> Apple : accepte, c'est normal.

Ensuite, tu peux relancer l'interface d'un simple **double-clic** sur
`Installer-mac.command` (ou `Lancer.command`).

### Méthode ZIP (téléchargement depuis GitHub)

1. Sur GitHub : bouton vert **Code → Download ZIP**, puis décompresse.
2. Ouvre le **Terminal**, va dans le dossier, et rends les scripts exécutables :
   ```bash
   cd ~/Downloads/mp3-main      # adapte le chemin
   chmod +x *.command
   ./Installer-mac.command
   ```

> ⚠️ **Pourquoi le double-clic ne marche pas après un ZIP ?**
> Le téléchargement ZIP de GitHub perd le « bit exécutable » des fichiers `.command`.
> La commande `chmod +x *.command` le remet — après ça, le double-clic fonctionne.

> ⚠️ **macOS bloque « développeur non identifié » ?**
> Clic droit sur le fichier → **Ouvrir** → **Ouvrir**. Une seule fois.

L'installateur met en place **Homebrew, Python, yt-dlp, ffmpeg et deno**, puis ouvre
l'interface dans ton navigateur. Colle tes liens → **Installer** → le ZIP se télécharge.

---

## Utilisation

- **Interface web** : `./Installer-mac.command` (ou `python3 app.py`) → ouvre la page.
- **En ligne de commande** : `./mp3dl.sh` puis colle les liens, Entrée, Ctrl-D.

Les MP3 arrivent dans le dossier `download/`.

---

## Déploiement serveur (Docker / Coolify)

```bash
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
