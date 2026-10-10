#!/usr/bin/env python3
"""
Interface web locale pour télécharger des musiques YouTube en MP3.

Lancer :  python3 app.py
Puis ouvrir http://localhost:8756 dans le navigateur.

Colle un ou plusieurs liens (séparés par ; , espace, retour à la ligne, "ou"…),
clique sur « Installer ». Playlist -> tout est téléchargé ; musique seule -> juste elle.
Les MP3 arrivent dans ./download, et un ZIP de la session est proposé au téléchargement.
"""
import base64
import hmac
import http.server
import socketserver
import os
import re
import subprocess
import threading
import json
import zipfile
import tempfile
import uuid
import datetime
from urllib.parse import urlparse, parse_qs

import sys

HOST = os.environ.get("HOST", "127.0.0.1")   # 0.0.0.0 en conteneur (voir docker-compose)
PORT = int(os.environ.get("PORT", "8756"))
HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.environ.get("DOWNLOAD_DIR", os.path.join(HERE, "download"))
# Cookies YouTube (contourne le "Sign in to confirm you're not a bot" sur un serveur)
COOKIES_FILE = os.environ.get("COOKIES_FILE") or os.path.join(HERE, "cookies.txt")
# Mot de passe optionnel pour envoyer des cookies depuis la page (conseillé si l'URL est publique)
COOKIES_PASSWORD = os.environ.get("COOKIES_PASSWORD", "")
COOKIES_MAX_SIZE = 1024 * 1024

YTDLP_FLAGS = [
    "--extract-audio",
    "--audio-format", "mp3",
    "--audio-quality", "0",
    "--embed-thumbnail",
    "--add-metadata",
    "--embed-metadata",
    "--ignore-errors",
    "--continue",
    "--no-overwrites",
    "--newline",
    "--output", os.path.join(DEST, "%(title)s.%(ext)s"),
]

URL_RE = re.compile(r"https?://[^\s;,\"']+")
# Récupère le chemin du mp3 final dans la sortie de yt-dlp
DEST_RE = re.compile(r"\[ExtractAudio\] Destination: (.+\.mp3)$")
ALREADY_RE = re.compile(r"\[download\] (.+\.mp3) has already been downloaded")
# Suivi de progression
ITEM_RE = re.compile(r"Downloading item (\d+) of (\d+)")      # playlists : N sur M
PCT_RE = re.compile(r"\[download\]\s+([\d.]+)% of")           # % du morceau en cours
DLDEST_RE = re.compile(r"\[download\] Destination: (.+)$")    # nom du morceau en cours

# Stocke les zip prêts : token -> chemin du fichier zip
ZIPS = {}

PAGE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MP3 Downloader</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; background: #0f1115; color: #e6e8eb;
    display: flex; justify-content: center; min-height: 100vh;
  }
  .wrap { width: 100%; max-width: 720px; padding: 40px 24px; }
  h1 { font-size: 26px; font-weight: 700; margin: 0 0 6px; }
  .sub { color: #8b93a1; margin: 0 0 28px; font-size: 14px; }
  textarea {
    width: 100%; min-height: 130px; resize: vertical; padding: 14px 16px;
    border-radius: 12px; border: 1px solid #2a2f3a; background: #171a21;
    color: #e6e8eb; font-size: 14px; line-height: 1.6; font-family: inherit;
  }
  textarea:focus { outline: none; border-color: #4f7cff; }
  .row { display: flex; gap: 12px; align-items: center; margin-top: 16px; flex-wrap: wrap; }
  button {
    background: #4f7cff; color: #fff; border: none; padding: 13px 26px;
    border-radius: 12px; font-size: 15px; font-weight: 600; cursor: pointer;
  }
  button:hover { background: #3d67e6; }
  button:disabled { background: #2a2f3a; color: #6b7280; cursor: not-allowed; }
  button.zip { background: #37d67a; color: #08240f; display: none; }
  button.zip:hover { background: #2cc06b; }
  button.zip.show { display: inline-block; }
  .count { color: #8b93a1; font-size: 13px; }
  .progress { margin-top: 24px; display: none; }
  .progress.show { display: block; }
  .pbar {
    height: 16px; background: #171a21; border: 1px solid #2a2f3a;
    border-radius: 999px; overflow: hidden;
  }
  .pfill {
    height: 100%; width: 0%; border-radius: 999px;
    background: linear-gradient(90deg, #4f7cff, #37d67a);
    transition: width .3s ease;
  }
  .pmeta {
    display: flex; justify-content: space-between; gap: 12px;
    margin-top: 10px; font-size: 13.5px;
  }
  .pcount { font-weight: 600; }
  .pcur { color: #8b93a1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
  .log {
    margin-top: 24px; background: #0a0c10; border: 1px solid #2a2f3a;
    border-radius: 12px; padding: 16px; font-family: ui-monospace, Menlo, monospace;
    font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-all;
    max-height: 340px; overflow-y: auto; display: none;
  }
  .log.show { display: block; }
  .done { color: #37d67a; } .err { color: #ff6b6b; } .info { color: #8b93a1; }
  .hint { margin-top: 14px; font-size: 12.5px; color: #6b7280; }
  code { background: #171a21; padding: 2px 6px; border-radius: 5px; }
  .cookies {
    margin-top: 28px; border: 1px solid #2a2f3a; border-radius: 12px;
    background: #171a21; padding: 14px 16px;
  }
  .cookies summary { cursor: pointer; font-weight: 600; font-size: 14px; }
  .cstatus { font-size: 13px; margin: 10px 0 0; }
  .cstatus.ok { color: #37d67a; } .cstatus.ko { color: #ffb84d; }
  .cookies .row { margin-top: 12px; }
  .cookies input[type=file] { color: #8b93a1; font-size: 13px; max-width: 100%; }
  .cookies input[type=password] {
    padding: 10px 12px; border-radius: 10px; border: 1px solid #2a2f3a;
    background: #0f1115; color: #e6e8eb; font-size: 14px;
  }
  .cookies button { padding: 10px 18px; font-size: 14px; }
  .cmsg { font-size: 13px; }
</style>
</head>
<body>
  <div class="wrap">
    <h1>🎵 MP3 Downloader</h1>
    <p class="sub">Colle tes liens YouTube et clique sur Installer. Playlist entière ou musique seule. Un ZIP est créé à la fin.</p>
    <textarea id="links" placeholder="Colle ici un ou plusieurs liens...
Exemple :
https://www.youtube.com/watch?v=biYdUZXfz9I ; https://youtu.be/q-3qus2pvJM"></textarea>
    <div class="row">
      <button id="go">Installer</button>
      <button id="zip" class="zip">⬇︎ Télécharger le ZIP</button>
      <span class="count" id="count"></span>
    </div>
    <p class="hint">Séparateurs acceptés : retour à la ligne, <code>;</code>, virgule, espace, « ou ». Les playlists entières sont téléchargées.</p>
    <div class="progress" id="prog">
      <div class="pbar"><div class="pfill" id="pfill"></div></div>
      <div class="pmeta">
        <span class="pcount" id="pcount">0 / 0 installées</span>
        <span class="pcur" id="pcur"></span>
      </div>
    </div>
    <div class="log" id="log"></div>
    <details class="cookies" id="cookies">
      <summary>🍪 Cookies YouTube</summary>
      <p class="cstatus" id="cstatus">Vérification...</p>
      <div class="row">
        <input type="file" id="cfile" accept=".txt,text/plain">
        <input type="password" id="cpass" placeholder="Mot de passe" style="display:none">
        <button id="csend">Envoyer</button>
        <span class="cmsg" id="cmsg"></span>
      </div>
      <p class="hint">Si YouTube répond « Sign in to confirm you're not a bot » : exporte un
      <code>cookies.txt</code> (navigation privée, connecté à YouTube, extension
      « Get cookies.txt LOCALLY ») et envoie-le ici. Il est conservé sur le serveur.</p>
    </details>
  </div>
<script>
const ta = document.getElementById('links');
const btn = document.getElementById('go');
const zipBtn = document.getElementById('zip');
const log = document.getElementById('log');
const count = document.getElementById('count');
const prog = document.getElementById('prog');
const pfill = document.getElementById('pfill');
const pcount = document.getElementById('pcount');
const pcur = document.getElementById('pcur');
let zipUrl = null;

function findUrls(t){ return (t.match(/https?:\\/\\/[^\\s;,"']+/g) || []); }

function updateProgress(done, total, pct, title){
  prog.className = 'progress show';
  const t = total > 0 ? total : 1;
  // progression globale = morceaux finis + fraction du morceau en cours
  const overall = Math.min(100, ((done + (pct/100)) / t) * 100);
  pfill.style.width = overall.toFixed(1) + '%';
  pcount.textContent = done + ' / ' + total + ' installées';
  pcur.textContent = title ? (pct < 100 && pct > 0 ? title + ' · ' + pct + '%' : title) : '';
}

ta.addEventListener('input', () => {
  const n = findUrls(ta.value).length;
  count.textContent = n ? n + ' lien(s) détecté(s)' : '';
});

function line(txt, cls){
  const d = document.createElement('div');
  if (cls) d.className = cls;
  d.textContent = txt;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
}

zipBtn.addEventListener('click', () => { if (zipUrl) window.location = zipUrl; });

// --- Cookies YouTube ---
const cstatus = document.getElementById('cstatus');
const cfile = document.getElementById('cfile');
const cpass = document.getElementById('cpass');
const csend = document.getElementById('csend');
const cmsg = document.getElementById('cmsg');

async function refreshCookies(){
  try {
    const st = await (await fetch('/cookies-status')).json();
    cpass.style.display = st.password_required ? '' : 'none';
    if (st.present){
      cstatus.className = 'cstatus ok';
      cstatus.textContent = '✅ Cookies présents (mis à jour le ' + st.updated + ')';
    } else {
      cstatus.className = 'cstatus ko';
      cstatus.textContent = '⚠️ Aucun cookies : YouTube risque de bloquer les téléchargements';
      document.getElementById('cookies').open = true;
    }
  } catch(e){ cstatus.textContent = 'Statut indisponible'; }
}

csend.addEventListener('click', async () => {
  const f = cfile.files[0];
  if (!f){ cmsg.className = 'cmsg err'; cmsg.textContent = 'Choisis un fichier cookies.txt'; return; }
  csend.disabled = true; cmsg.className = 'cmsg info'; cmsg.textContent = 'Envoi...';
  try {
    const res = await fetch('/cookies', {
      method: 'POST',
      headers: {'Content-Type': 'text/plain', 'X-Cookies-Password': cpass.value},
      body: f
    });
    const txt = await res.text();
    cmsg.className = res.ok ? 'cmsg done' : 'cmsg err';
    cmsg.textContent = txt;
    if (res.ok){ cfile.value = ''; refreshCookies(); }
  } catch(e){
    cmsg.className = 'cmsg err'; cmsg.textContent = 'Erreur : ' + e.message;
  }
  csend.disabled = false;
});

refreshCookies();

btn.addEventListener('click', async () => {
  const urls = findUrls(ta.value);
  if (!urls.length){ alert('Aucun lien détecté.'); return; }
  btn.disabled = true; btn.textContent = 'Téléchargement...';
  zipBtn.className = 'zip'; zipUrl = null;
  log.className = 'log show'; log.innerHTML = '';
  prog.className = 'progress'; pfill.style.width = '0%';
  pcount.textContent = '0 / 0 installées'; pcur.textContent = '';
  line('Démarrage de ' + urls.length + ' lien(s)...', 'info');

  try {
    const res = await fetch('/download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({urls})
    });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true){
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      const parts = buf.split('\\n');
      buf = parts.pop();
      for (const p of parts){
        if (!p) continue;
        if (p.startsWith('##ZIP##')){
          const tok = p.slice(7).trim();
          if (tok){
            zipUrl = '/get-zip?token=' + encodeURIComponent(tok);
            zipBtn.className = 'zip show';
            line('📦 ZIP prêt — téléchargement...', 'done');
            window.location = zipUrl;   // déclenche le téléchargement du zip
          }
          continue;
        }
        if (p.startsWith('##PROG##')){
          const parts2 = p.slice(8).split('|');
          updateProgress(parseInt(parts2[0])||0, parseInt(parts2[1])||0,
                         parseInt(parts2[2])||0, parts2[3]||'');
          continue;
        }
        if (p.startsWith('##NONE##')){ line('Aucun nouveau fichier à zipper.', 'info'); continue; }
        let cls = '';
        if (p.startsWith('[ExtractAudio]') || p.includes('has already been downloaded')) cls = 'done';
        else if (p.toLowerCase().includes('error')) cls = 'err';
        line(p, cls);
      }
    }
    if (prog.classList.contains('show')){ pfill.style.width = '100%'; pcur.textContent = ''; }
    line('✅ Terminé. Fichiers dans le dossier download.', 'done');
  } catch(e){
    line('Erreur : ' + e.message, 'err');
  }
  btn.disabled = false; btn.textContent = 'Installer';
});
</script>
</body>
</html>"""


def make_zip(files):
    """Crée un zip des fichiers donnés, renvoie (token, chemin) ou (None, None)."""
    files = [f for f in files if f and os.path.isfile(f)]
    if not files:
        return None, None
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zpath = os.path.join(tempfile.gettempdir(), f"musiques_{stamp}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(f, arcname=os.path.basename(f))
    token = uuid.uuid4().hex
    ZIPS[token] = zpath
    return token, zpath


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence les logs par requête

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/cookies-status":
            present = os.path.isfile(COOKIES_FILE)
            updated = ""
            if present:
                mtime = os.path.getmtime(COOKIES_FILE)
                updated = datetime.datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            self.send_json({
                "present": present,
                "updated": updated,
                "password_required": bool(COOKIES_PASSWORD),
            })
        elif parsed.path == "/get-zip":
            qs = parse_qs(parsed.query)
            token = (qs.get("token") or [""])[0]
            zpath = ZIPS.get(token)
            if not zpath or not os.path.isfile(zpath):
                self.send_error(404, "zip introuvable")
                return
            size = os.path.getsize(zpath)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{os.path.basename(zpath)}"',
            )
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(zpath, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        break
        else:
            self.send_error(404)

    def send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def upload_cookies(self):
        """Reçoit un cookies.txt (format Netscape) depuis la page et le remplace sur le disque."""
        if COOKIES_PASSWORD:
            given = self.headers.get("X-Cookies-Password", "")
            if not hmac.compare_digest(given.encode("utf-8"), COOKIES_PASSWORD.encode("utf-8")):
                self.send_text(403, "Mot de passe incorrect")
                return
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > COOKIES_MAX_SIZE:
            self.send_text(400, "Fichier vide ou trop gros")
            return
        data = self.rfile.read(length)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            self.send_text(400, "Ce n'est pas un fichier texte")
            return
        # Format Netscape : 7 champs séparés par des tabulations, au moins un cookie YouTube
        rows = [l.split("\t") for l in text.splitlines() if l and not l.startswith("# ")]
        if not any(len(r) == 7 and "youtube.com" in r[0] for r in rows):
            self.send_text(400, "Format invalide : exporte un cookies.txt (Netscape) depuis youtube.com")
            return
        if not text.startswith("# Netscape HTTP Cookie File") and not text.startswith("# HTTP Cookie File"):
            text = "# Netscape HTTP Cookie File\n" + text  # en-tête exigé par yt-dlp
        os.makedirs(os.path.dirname(COOKIES_FILE) or ".", exist_ok=True)
        tmp = COOKIES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, COOKIES_FILE)
        print("  🍪 Cookies mis à jour depuis la page", flush=True)
        self.send_text(200, "✅ Cookies enregistrés")

    def do_POST(self):
        if self.path == "/cookies":
            self.upload_cookies()
            return
        if self.path != "/download":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            urls = data.get("urls", [])
        except Exception:
            urls = []
        # Filtre de sécurité : on ne garde que de vraies URLs
        urls = [u for u in urls if URL_RE.fullmatch(u.strip())]
        if not urls:
            self.send_error(400, "no urls")
            return

        os.makedirs(DEST, exist_ok=True)
        # Photo du dossier AVANT, pour détecter les nouveaux fichiers ensuite
        before = set()
        for f in os.listdir(DEST):
            if f.lower().endswith(".mp3"):
                before.add(os.path.join(DEST, f))

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        produced = set()  # chemins mp3 issus de CETTE session
        cmd = ["yt-dlp"] + YTDLP_FLAGS
        # Cookies YouTube (si fournis) : contourne le "Sign in to confirm you're not a bot"
        if os.path.isfile(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]
            cookies_msg = "🍪 Cookies utilisés\n"
        else:
            cookies_msg = "⚠️ Aucun cookies : YouTube risque de bloquer (envoie un cookies.txt en bas de la page)\n"
        cmd += urls
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )

        # État de progression
        total = len(urls)   # au minimum le nombre de liens ; ajusté si playlist
        done = 0            # morceaux terminés
        cur_title = ""      # nom du morceau en cours
        cur_pct = 0         # % de téléchargement du morceau en cours
        last_sent = -1      # dernier % envoyé (throttle)

        def send(text):
            self.wfile.write(text.encode("utf-8", "replace"))
            self.wfile.flush()

        def emit_prog():
            name = os.path.splitext(os.path.basename(cur_title))[0]  # sans extension
            name = name.replace("|", "-")  # évite de casser le séparateur du message
            send(f"##PROG##{done}|{total}|{int(cur_pct)}|{name}\n")

        try:
            send(cookies_msg)
            for out_line in iter(proc.stdout.readline, ""):
                out_line = out_line.rstrip("\n")

                # Playlist : "Downloading item N of M" -> total = M
                mi = ITEM_RE.search(out_line)
                if mi:
                    total = max(total, int(mi.group(2)))
                    emit_prog()

                # Nouveau morceau en cours de téléchargement
                md = DLDEST_RE.search(out_line)
                if md and not md.group(1).endswith(".mp3"):
                    cur_title = md.group(1)
                    cur_pct = 0
                    last_sent = -1
                    emit_prog()

                # % de téléchargement du morceau en cours (throttlé au %)
                mp = PCT_RE.search(out_line)
                if mp:
                    cur_pct = float(mp.group(1))
                    if int(cur_pct) != last_sent:
                        last_sent = int(cur_pct)
                        emit_prog()
                    continue  # ne pas polluer le log avec les lignes de %

                # Morceau terminé (converti en mp3, ou déjà présent)
                mfin = DEST_RE.search(out_line) or ALREADY_RE.search(out_line)
                if mfin:
                    produced.add(mfin.group(1))
                    done += 1
                    cur_pct = 100
                    if done > total:
                        total = done
                    emit_prog()

                try:
                    send(out_line + "\n")
                except (BrokenPipeError, ConnectionResetError):
                    proc.kill()
                    break
            proc.wait()
        except (BrokenPipeError, ConnectionResetError):
            proc.kill()
        finally:
            if proc.stdout:
                proc.stdout.close()

        # Fichiers de la session = ceux repérés dans la sortie + nouveaux fichiers du dossier
        after = set()
        for f in os.listdir(DEST):
            if f.lower().endswith(".mp3"):
                after.add(os.path.join(DEST, f))
        produced |= (after - before)

        token, _ = make_zip(sorted(produced))
        try:
            if token:
                self.wfile.write(f"##ZIP##{token}\n".encode("utf-8"))
            else:
                self.wfile.write(b"##NONE##\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def install_cookies_from_env():
    """Coolify : YT_COOKIES_B64 (cookies.txt encodé en base64) -> écrit dans COOKIES_FILE."""
    b64 = os.environ.get("YT_COOKIES_B64", "").strip()
    path = COOKIES_FILE
    if not b64:
        return
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception as e:
        print(f"  ⚠️  YT_COOKIES_B64 invalide (base64 attendu) : {e}", flush=True)
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"  🍪 Cookies installés depuis YT_COOKIES_B64 -> {path}", flush=True)


def start_server():
    """Démarre le serveur ; si le port est occupé, en essaie un autre au lieu de planter."""
    last_err = None
    for port in range(PORT, PORT + 10):
        try:
            httpd = Server((HOST, port), Handler)
        except OSError as e:
            last_err = e
            continue  # port occupé -> on tente le suivant
        return httpd, port
    raise SystemExit(f"Impossible d'ouvrir un port libre ({PORT}-{PORT + 9}) : {last_err}")


if __name__ == "__main__":
    os.makedirs(DEST, exist_ok=True)
    install_cookies_from_env()
    httpd, port = start_server()
    url = f"http://localhost:{port}"
    print(f"\n  🎵 MP3 Downloader lancé sur  {HOST}:{port}")
    print(f"  🌐 Ouvre dans le navigateur : {url}")
    print(f"  📁 Destination : {DEST}")
    print("  (Ctrl-C pour arrêter)\n", flush=True)
    # Ouvre le navigateur seulement en local sur macOS (pas dans un conteneur)
    if sys.platform == "darwin" and HOST in ("127.0.0.1", "localhost"):
        try:
            threading.Timer(0.7, lambda: subprocess.run(["open", url])).start()
        except Exception:
            pass
    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nArrêté.")
