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
   - Exporte un `cookies.txt` : **fenêtre de navigation privée**, connecte-toi à
     YouTube, va sur `https://www.youtube.com/robots.txt`, exporte avec l'extension
     « Get cookies.txt LOCALLY », puis **ferme la fenêtre privée**.
   - Envoie-le depuis la page : panneau **🍪 Cookies YouTube** en bas → choisis le
     fichier → **Envoyer**. Il est conservé dans le volume `mp3-config`.
   - Conseillé : définis `COOKIES_PASSWORD` dans Coolify → **Environment Variables**
     pour que personne d'autre ne puisse remplacer tes cookies.
   - Alternative : `YT_COOKIES_B64` = sortie de
     `base64 -i ~/Downloads/cookies.txt | tr -d '\n' | pbcopy`. Elle est réécrite à
     chaque démarrage et écrase donc les cookies envoyés depuis la page : laisse-la
     vide si tu utilises le panneau.
   - **Ou, plus simple : connexion automatique** (voir ci-dessous) — plus besoin
     d'exporter des cookies à la main.
5. **Deploy**. Les MP3 sont déposés dans **`/srv/media/music/YouTube`** sur le serveur,
   c'est-à-dire dans la bibliothèque **Navidrome** (montée en `/music`) : ils
   apparaissent dans Navidrome et Amperfy après le scan. Ils appartiennent à
   `PUID:PGID` (1000:1000 = `ubuntu` par défaut). Pour un autre dossier, modifie le
   volume `/srv/media/music/YouTube:/app/download` dans `docker-compose.yml`.

### Installations en arrière-plan

Chaque clic sur **Installer** crée une installation côté serveur : on peut rafraîchir
ou fermer la page, elle continue. La section **Installations** liste celles en attente,
en cours et terminées (progression, journal, bouton Stopper, ZIP), pendant 24 h.
`MAX_PARALLEL` (2 par défaut) fixe le nombre d'installations simultanées ; les
suivantes attendent leur tour.

### Connexion automatique au compte YouTube

Renseigne dans Coolify → **Environment Variables** :

| Variable | Rôle |
|---|---|
| `GOOGLE_EMAIL` | adresse Gmail du compte |
| `GOOGLE_PASSWORD` | mot de passe |
| `GOOGLE_TOTP_SECRET` | *(optionnel)* secret de l'appli d'authentification si la validation en 2 étapes est active (la clé affichée sous le QR code, « Impossible de scanner ? ») |
| `COOKIES_REFRESH_HOURS` | *(optionnel)* fréquence de rafraîchissement, 12 h par défaut |

Le serveur se connecte avec un navigateur headless (**Camoufox**, un Firefox que Google
accepte, contrairement au navigateur standard de Playwright), récupère les cookies et
les rafraîchit tout seul : au démarrage, toutes les `COOKIES_REFRESH_HOURS`, et dès que
YouTube répond « Sign in to confirm you're not a bot » (l'installation est alors
relancée automatiquement). Le profil du navigateur est gardé dans le volume
`mp3-config`, donc le mot de passe n'est retapé que si la session expire.

**Première connexion** : depuis un serveur inconnu, Google demande souvent une
vérification (numéro de téléphone, code SMS, captcha). Le panneau **🍪 Cookies YouTube**
affiche alors l'écran du navigateur en direct : clique dedans, tape le code demandé,
Entrée. C'est à faire une fois ; la session est ensuite conservée. En cas d'échec, une
capture d'écran est disponible dans le panneau et un nouvel essai automatique n'a lieu
qu'après 30 min (bouton **Reconnecter maintenant** pour forcer).

> ⚠️ Utilise un **compte secondaire** dédié : YouTube peut restreindre un compte
> utilisé avec yt-dlp. Définis `COOKIES_PASSWORD` : il protège aussi le bouton
> Reconnecter et le pilotage du navigateur de connexion.

> ⚠️ L'interface n'a pas d'authentification : protège-la (Basic Auth Traefik dans
> Coolify par exemple) si l'URL est publique.

En Docker local (hors Coolify), remplace `expose` par `ports: ["8756:8756"]` et
`/srv/media/music/YouTube` par `./download` dans `docker-compose.yml`, puis à la racine
du dossier :

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
