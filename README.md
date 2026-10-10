# 🎵 MP3 Downloader

Télécharge des musiques YouTube en MP3 (320 kbps, pochette + métadonnées) via une
petite interface web locale. Colle un ou plusieurs liens (playlist ou musique seule),
clique sur **Installer**, et récupère un **ZIP** de tes morceaux.

## Contenu du dossier

```
run.command         ← le seul fichier à lancer (installe tout puis ouvre l'interface)
download/           ← tes MP3 téléchargés
app/                ← le code (tu n'as pas besoin d'y toucher)
Dockerfile          ← déploiement serveur (Docker / Coolify)
docker-compose.yml
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

## Déploiement serveur (Coolify)

1. **New Resource → Repository GitHub** `Murathan-Aydin/mp3`, branche `main`.
2. **Build Pack : Docker Compose**
   - Base Directory : `/` (valeur par défaut)
   - Docker Compose Location : `/docker-compose.yml` (valeur par défaut)
3. **Domaine** du service `mp3downloader` : `https://mp3.ton-domaine.fr:8756`
   (le `:8756` indique au proxy le port interne ; il n'apparaît pas dans l'URL publique).
4. **Cookies YouTube** : sur un serveur, YouTube demande souvent une authentification
   (« confirm you're not a bot »).
   - Ouvre une **fenêtre de navigation privée**, connecte-toi à YouTube, va sur
     `https://www.youtube.com/robots.txt`, exporte les cookies avec l'extension
     « Get cookies.txt LOCALLY », puis **ferme la fenêtre privée**.
   - Sur ton Mac, encode le fichier en base64 (copié dans le presse-papier) :
     ```bash
     base64 -i ~/Downloads/cookies.txt | tr -d '\n' | pbcopy
     ```
   - Dans Coolify : **Environment Variables** → `YT_COOKIES_B64` = colle la valeur.
   - Au démarrage, l'app écrit les cookies dans le volume `mp3-config`
     (`/app/config/cookies.txt`). Le log de chaque téléchargement indique
     « 🍪 Cookies utilisés » ou « ⚠️ Aucun cookies.txt trouvé ».
5. **Deploy**. Les MP3 sont conservés dans le volume `mp3-downloads`.
   Pour changer de cookies : modifie `YT_COOKIES_B64` puis **Redeploy**.

> ⚠️ L'interface n'a pas d'authentification : protège-la (Basic Auth Traefik dans
> Coolify par exemple) si l'URL est publique.

En Docker local (hors Coolify), remplace `expose` par `ports: ["8756:8756"]` dans
`docker-compose.yml`, puis à la racine du dossier :

```bash
docker compose up -d --build
```

---

## Mise à jour de yt-dlp

YouTube change souvent ; si les téléchargements échouent, mets yt-dlp à jour :

```bash
brew upgrade yt-dlp     # installation locale Mac
```

---

## ⚠️ Usage

À réserver à un usage **personnel/privé**. Ne redistribue pas de contenu protégé.
