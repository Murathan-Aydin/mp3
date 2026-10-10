#!/usr/bin/env python3
"""
Interface web locale pour télécharger des musiques YouTube en MP3.

Lancer :  python3 app.py
Puis ouvrir http://localhost:8756 dans le navigateur.

Colle un ou plusieurs liens (séparés par ; , espace, retour à la ligne, "ou"…),
clique sur « Installer ». Playlist -> tout est téléchargé ; musique seule -> juste elle.
Les téléchargements tournent en arrière-plan côté serveur : on peut rafraîchir ou
fermer la page, ils continuent et restent visibles dans « Installations ».
Les MP3 arrivent dans ./download, et un ZIP de chaque installation est proposé.

Avec GOOGLE_EMAIL + GOOGLE_PASSWORD, les cookies YouTube sont récupérés
automatiquement (voir ytlogin.py).
"""
import base64
import hmac
import http.server
import socketserver
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import json
import zipfile
import tempfile
import uuid
import datetime
import importlib.util
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
COOKIES_MAX_SIZE = 3 * 1024 * 1024
# Connexion automatique au compte Google (ytlogin.py) : cookies récupérés tout seuls
GOOGLE_EMAIL = os.environ.get("GOOGLE_EMAIL", "").strip()
AUTO_LOGIN = bool(GOOGLE_EMAIL and os.environ.get("GOOGLE_PASSWORD"))
LOGIN_SCRIPT = os.path.join(HERE, "ytlogin.py")
LOGIN_SCREENSHOT = os.path.join(os.path.dirname(COOKIES_FILE) or ".", "login-debug.png")
COOKIES_REFRESH = float(os.environ.get("COOKIES_REFRESH_HOURS", "12")) * 3600
LOGIN_TIMEOUT = 900    # durée max d'une connexion (assistance manuelle comprise)
LOGIN_BACKOFF = 1800   # après un échec, pas de nouvel essai automatique avant 30 min
# Propriétaire des MP3 (ex. bibliothèque Navidrome sur l'hôte) : sinon ils restent à root
PUID = os.environ.get("PUID", "")
PGID = os.environ.get("PGID", "")
ZIP_TTL = 3600  # les ZIP sont supprimés au bout d'1 h (économise le disque)
MAX_PARALLEL = max(1, int(os.environ.get("MAX_PARALLEL", "2")))  # installations simultanées
JOB_TTL = 24 * 3600   # les installations terminées restent affichées 24 h
JOB_MAX = 50          # ... dans la limite des 50 plus récentes
LOG_MAX = 3000        # lignes de journal gardées par installation

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
# YouTube exige une connexion -> reconnexion automatique puis nouvel essai
BOT_RE = re.compile(r"Sign in to confirm|confirm you.re not a bot|cookies are no longer valid", re.I)

# Stocke les zip prêts : token -> chemin du fichier zip
ZIPS = {}
# Installations (en attente, en cours, terminées) : id -> Job
JOBS = {}
JOBS_LOCK = threading.Lock()
RUN_SLOTS = threading.Semaphore(MAX_PARALLEL)
# État de la connexion automatique, affiché dans le panneau cookies
LOGIN = {"state": "off", "message": "", "last_ok": "", "last_try": "", "failed_at": 0.0}
LOGIN_LOCK = threading.Lock()
LOGIN_PROC = None      # ytlogin.py en cours : reçoit les actions du mode assistance

PAGE = r"""<!doctype html>
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
  h2 {
    font-size: 17px; margin: 34px 0 12px; display: flex;
    justify-content: space-between; align-items: center; gap: 12px;
  }
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
  button.small { padding: 8px 14px; font-size: 13px; border-radius: 10px; }
  button.ghost { background: transparent; color: #8b93a1; border: 1px solid #2a2f3a; }
  button.ghost:hover { color: #e6e8eb; border-color: #4a5160; }
  button.zip { background: #37d67a; color: #08240f; }
  button.zip:hover { background: #2cc06b; }
  button.stop { background: #ff6b6b; color: #2a0808; }
  button.stop:hover { background: #e85a5a; }
  .hidden { display: none !important; }
  .count { color: #8b93a1; font-size: 13px; }
  .empty { color: #6b7280; font-size: 14px; margin: 0; }
  .job {
    border: 1px solid #2a2f3a; border-radius: 12px; background: #171a21;
    padding: 14px 16px; margin-bottom: 12px;
  }
  .jhead { display: flex; align-items: center; gap: 10px; font-size: 13.5px; }
  .jlabel { flex: 1; color: #c3c8d0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .jtime { color: #6b7280; font-size: 12.5px; white-space: nowrap; }
  .badge {
    font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 999px;
    white-space: nowrap; background: #2a2f3a; color: #c3c8d0;
  }
  .badge.running { background: #1d2b52; color: #8fb0ff; }
  .badge.done { background: #123222; color: #37d67a; }
  .badge.stopped { background: #3a2e14; color: #ffb84d; }
  .badge.error { background: #3a1616; color: #ff6b6b; }
  .pbar {
    height: 12px; background: #0f1115; border: 1px solid #2a2f3a;
    border-radius: 999px; overflow: hidden; margin-top: 12px;
  }
  .pfill {
    height: 100%; width: 0%; border-radius: 999px;
    background: linear-gradient(90deg, #4f7cff, #37d67a);
    transition: width .3s ease;
  }
  .pmeta {
    display: flex; justify-content: space-between; gap: 12px;
    margin-top: 8px; font-size: 13px;
  }
  .pcount { font-weight: 600; white-space: nowrap; }
  .pcur { color: #8b93a1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .jerr { font-size: 13px; margin-top: 8px; }
  .job .row { margin-top: 12px; gap: 8px; }
  .log {
    margin-top: 12px; background: #0a0c10; border: 1px solid #2a2f3a;
    border-radius: 12px; padding: 14px; font-family: ui-monospace, Menlo, monospace;
    font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-all;
    max-height: 300px; overflow-y: auto;
  }
  .done { color: #37d67a; } .err { color: #ff6b6b; } .info { color: #8b93a1; }
  .hint { margin-top: 14px; font-size: 12.5px; color: #6b7280; }
  code { background: #0f1115; padding: 2px 6px; border-radius: 5px; }
  .cookies {
    margin-top: 28px; border: 1px solid #2a2f3a; border-radius: 12px;
    background: #171a21; padding: 14px 16px;
  }
  .cookies summary { cursor: pointer; font-weight: 600; font-size: 14px; }
  .cstatus { font-size: 13px; margin: 10px 0 0; }
  .cstatus.ok { color: #37d67a; } .cstatus.ko { color: #ffb84d; }
  .auto {
    margin-top: 12px; padding: 12px; border-radius: 10px; background: #0f1115;
    border: 1px solid #2a2f3a; font-size: 13px; line-height: 1.6;
  }
  .auto a { color: #8fb0ff; }
  .assist { margin-top: 12px; }
  .assist img {
    width: 100%; border-radius: 8px; border: 2px solid #4f7cff;
    cursor: crosshair; display: block; background: #fff;
  }
  .assist input[type=text] {
    flex: 1; min-width: 160px; padding: 9px 12px; border-radius: 10px;
    border: 1px solid #2a2f3a; background: #171a21; color: #e6e8eb; font-size: 14px;
  }
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
    <p class="sub">Colle tes liens YouTube et clique sur Installer. Les installations continuent en arrière-plan même si tu fermes ou rafraîchis la page.</p>
    <textarea id="links" placeholder="Colle ici un ou plusieurs liens...
Exemple :
https://www.youtube.com/watch?v=biYdUZXfz9I ; https://youtu.be/q-3qus2pvJM"></textarea>
    <div class="row">
      <button id="go">Installer</button>
      <span class="count" id="count"></span>
    </div>
    <p class="hint">Séparateurs acceptés : retour à la ligne, <code>;</code>, virgule, espace, « ou ». Les playlists entières sont téléchargées.</p>

    <h2>Installations <button id="clear" class="small ghost hidden">Effacer les terminées</button></h2>
    <div id="jobs"><p class="empty" id="empty">Aucune installation pour l'instant.</p></div>

    <details class="cookies" id="cookies">
      <summary>🍪 Cookies YouTube</summary>
      <p class="cstatus" id="cstatus">Vérification...</p>
      <div class="auto hidden" id="auto">
        <div id="autotxt"></div>
        <div class="row">
          <button id="crefresh" class="small">🔄 Reconnecter maintenant</button>
          <a id="cshot" class="hidden" href="/login-screenshot" target="_blank">Voir la capture de l'erreur</a>
        </div>
        <div class="assist hidden" id="assist">
          <p class="hint">🙋 Google demande une vérification : clique dans l'écran ci-dessous comme
          sur un vrai navigateur, tape le texte demandé puis Entrée. À faire une seule fois :
          la session est ensuite conservée.</p>
          <img id="ashot" alt="Écran du navigateur de connexion">
          <div class="row">
            <input type="text" id="atext" placeholder="Texte à taper (numéro, code SMS...)" autocomplete="off">
            <button id="atype" class="small">Taper</button>
            <button id="aenter" class="small ghost">Entrée ⏎</button>
            <button id="aback" class="small ghost">Effacer</button>
          </div>
        </div>
      </div>
      <div class="row">
        <input type="file" id="cfile" accept=".txt,text/plain">
        <input type="password" id="cpass" placeholder="Mot de passe" style="display:none">
        <button id="csend">Envoyer</button>
        <span class="cmsg" id="cmsg"></span>
      </div>
      <p class="hint">Si YouTube répond « Sign in to confirm you're not a bot » : exporte un
      <code>cookies.txt</code> (navigation privée, connecté à YouTube, extension
      « Get cookies.txt LOCALLY ») et envoie-le ici, ou configure la connexion automatique
      (<code>GOOGLE_EMAIL</code> / <code>GOOGLE_PASSWORD</code>). Il est conservé sur le serveur.</p>
    </details>
  </div>
<script>
const $ = id => document.getElementById(id);
const ta = $('links'), btn = $('go'), count = $('count');
const jobsBox = $('jobs'), empty = $('empty'), clearBtn = $('clear');
const STATUS = {queued: 'En attente', running: 'En cours', done: 'Terminé',
                stopped: 'Arrêté', error: 'Erreur'};
const cards = {};          // id -> éléments de la carte
const logs = {};           // id -> index de la prochaine ligne de journal (si ouvert)
const seenActive = new Set();   // installations vues en cours depuis cette page
const zipped = new Set();       // ZIP déjà téléchargés automatiquement

function findUrls(t){ return (t.match(/https?:\/\/[^\s;,"']+/g) || []); }
function isActive(j){ return j.status === 'queued' || j.status === 'running'; }
function hhmm(ts){ return new Date(ts * 1000).toLocaleTimeString('fr-FR', {hour: '2-digit', minute: '2-digit'}); }

ta.addEventListener('input', () => {
  const n = findUrls(ta.value).length;
  count.textContent = n ? n + ' lien(s) détecté(s)' : '';
});

async function post(url, obj){
  return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                     body: JSON.stringify(obj || {})});
}

function el(tag, cls, parent){
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (parent) parent.appendChild(e);
  return e;
}

function download(url){
  const a = el('a'); a.href = url; a.download = '';
  document.body.appendChild(a); a.click(); a.remove();
}

function makeCard(id){
  const c = {root: el('div', 'job')};
  const head = el('div', 'jhead', c.root);
  c.badge = el('span', 'badge', head);
  c.label = el('span', 'jlabel', head);
  c.time = el('span', 'jtime', head);
  c.bar = el('div', 'pbar', c.root);
  c.fill = el('div', 'pfill', c.bar);
  const meta = el('div', 'pmeta', c.root);
  c.count = el('span', 'pcount', meta);
  c.cur = el('span', 'pcur', meta);
  c.err = el('div', 'jerr err', c.root);
  const row = el('div', 'row', c.root);
  c.stop = el('button', 'small stop', row); c.stop.textContent = '⏹ Stopper';
  c.zip = el('button', 'small zip', row); c.zip.textContent = '⬇︎ ZIP';
  c.logBtn = el('button', 'small ghost', row); c.logBtn.textContent = 'Journal';
  c.remove = el('button', 'small ghost', row); c.remove.textContent = '✕ Retirer';
  c.log = el('div', 'log hidden', c.root);

  c.stop.onclick = async () => {
    c.stop.disabled = true; c.stop.textContent = 'Arrêt...';
    await post('/stop', {job: id}).catch(() => {});
  };
  c.zip.onclick = () => { if (c.zipUrl) download(c.zipUrl); };
  c.logBtn.onclick = () => toggleLog(id, c.log.classList.contains('hidden'));
  c.remove.onclick = async () => { await post('/remove', {job: id}).catch(() => {}); poll(true); };
  return c;
}

function toggleLog(id, open){
  const c = cards[id]; if (!c) return;
  c.log.classList.toggle('hidden', !open);
  c.logBtn.textContent = open ? 'Masquer le journal' : 'Journal';
  if (open && !(id in logs)){ logs[id] = 0; c.log.innerHTML = ''; pullLog(id); }
  if (!open){ delete logs[id]; }
}

function logLine(box, txt){
  const d = el('div');
  if (txt.startsWith('[ExtractAudio]') || txt.includes('has already been downloaded')
      || txt.startsWith('✅') || txt.startsWith('📦')) d.className = 'done';
  else if (txt.toLowerCase().includes('error') || txt.startsWith('❌')) d.className = 'err';
  else if (/^[🍪⚠️🔑⏹]/u.test(txt)) d.className = 'info';
  d.textContent = txt;
  box.appendChild(d);
}

async function pullLog(id){
  const c = cards[id]; if (!c || !(id in logs)) return;
  try {
    const r = await (await fetch('/job-log?id=' + id + '&since=' + logs[id])).json();
    const stick = c.log.scrollTop + c.log.clientHeight >= c.log.scrollHeight - 30;
    for (const l of r.lines) logLine(c.log, l);
    logs[id] = r.next;
    if (stick) c.log.scrollTop = c.log.scrollHeight;
  } catch(e){}
}

function updateCard(c, j){
  c.badge.className = 'badge ' + j.status;
  c.badge.textContent = STATUS[j.status] || j.status;
  c.label.textContent = j.label + (j.links > 1 ? '  (+' + (j.links - 1) + ' lien(s))' : '');
  c.label.title = j.label;
  c.time.textContent = hhmm(j.created) + (j.finished ? ' → ' + hhmm(j.finished) : '');
  const active = isActive(j);
  const t = j.total > 0 ? j.total : 1;
  let overall = Math.min(100, ((j.done + (active ? j.pct / 100 : 0)) / t) * 100);
  if (j.status === 'done') overall = 100;
  c.fill.style.width = overall.toFixed(1) + '%';
  c.count.textContent = j.done + ' / ' + j.total + ' installée(s)';
  c.cur.textContent = active ? (j.title ? (j.pct > 0 && j.pct < 100 ? j.title + ' · ' + j.pct + '%' : j.title)
                                        : (j.status === 'queued' ? 'En attente d\'une place...' : 'Démarrage...'))
                             : '';
  c.err.textContent = j.error || '';
  c.err.classList.toggle('hidden', !j.error);
  c.stop.classList.toggle('hidden', !active);
  if (active && !j.stopping){ c.stop.disabled = false; c.stop.textContent = '⏹ Stopper'; }
  c.zipUrl = j.zip ? '/get-zip?token=' + encodeURIComponent(j.zip) : null;
  c.zip.classList.toggle('hidden', !c.zipUrl);
  c.remove.classList.toggle('hidden', active);
}

function renderJobs(jobs){
  const ids = new Set(jobs.map(j => j.id));
  for (const id in cards){
    if (!ids.has(id)){ cards[id].root.remove(); delete cards[id]; delete logs[id]; }
  }
  let prev = null;
  for (const j of jobs){        // du plus récent au plus ancien
    let c = cards[j.id];
    if (!c){ c = cards[j.id] = makeCard(j.id); }
    if (prev ? prev.root.nextSibling !== c.root : jobsBox.firstChild !== c.root){
      jobsBox.insertBefore(c.root, prev ? prev.root.nextSibling : jobsBox.firstChild);
    }
    updateCard(c, j);
    prev = c;
    if (isActive(j)) seenActive.add(j.id);
    // Installation suivie depuis cette page et terminée : on récupère le ZIP tout seul
    else if (seenActive.has(j.id) && j.zip && !zipped.has(j.id)){
      zipped.add(j.id); download(c.zipUrl);
    }
  }
  empty.classList.toggle('hidden', jobs.length > 0);
  clearBtn.classList.toggle('hidden', !jobs.some(j => !isActive(j)));
  return jobs.some(isActive);
}

// --- Cookies YouTube ---
const cstatus = $('cstatus'), cfile = $('cfile'), cpass = $('cpass');
const csend = $('csend'), cmsg = $('cmsg'), crefresh = $('crefresh');
let cookiesSeen = false;

function renderCookies(st){
  cpass.style.display = st.password_required ? '' : 'none';
  if (st.present){
    cstatus.className = 'cstatus ok';
    cstatus.textContent = '✅ Cookies présents (mis à jour le ' + st.updated + ')';
  } else {
    cstatus.className = 'cstatus ko';
    cstatus.textContent = '⚠️ Aucun cookies : YouTube risque de bloquer les téléchargements';
  }
  const a = st.auto;
  $('auto').classList.toggle('hidden', !a.enabled);
  if (a.enabled){
    const icon = {running: '⏳', assist: '🙋', ok: '✅', error: '❌'}[a.state] || '🔑';
    const box = $('autotxt'), b = el('b');
    b.textContent = a.account;
    box.replaceChildren('🔑 Connexion automatique : ', b, el('br'),
                        icon + ' ' + (a.message || 'En attente'));
    if (a.last_ok) box.append(el('br'), 'Dernière connexion réussie : ' + a.last_ok);
    crefresh.disabled = a.state === 'running' || a.state === 'assist';
    $('cshot').classList.toggle('hidden', !a.screenshot);
    const assisting = a.state === 'assist';
    $('assist').classList.toggle('hidden', !assisting);
    if (assisting){
      $('cookies').open = true;
      $('ashot').src = '/login-screenshot?t=' + Date.now();
    }
  }
  if (!cookiesSeen){
    cookiesSeen = true;
    if (!st.present || (a.enabled && a.state === 'error')) $('cookies').open = true;
  }
}

crefresh.addEventListener('click', async () => {
  crefresh.disabled = true;
  const res = await fetch('/cookies-refresh', {method: 'POST',
                          headers: {'X-Cookies-Password': cpass.value}}).catch(() => null);
  if (res && !res.ok){ cmsg.className = 'cmsg err'; cmsg.textContent = await res.text(); }
  poll(true);
});

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
    if (res.ok){ cfile.value = ''; poll(true); }
  } catch(e){
    cmsg.className = 'cmsg err'; cmsg.textContent = 'Erreur : ' + e.message;
  }
  csend.disabled = false;
});

// --- Mode assistance : on pilote le navigateur de connexion depuis la page ---
async function assistAction(obj){
  const res = await fetch('/login-input', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Cookies-Password': cpass.value},
    body: JSON.stringify(obj)}).catch(() => null);
  if (res && !res.ok){ cmsg.className = 'cmsg err'; cmsg.textContent = await res.text(); }
  setTimeout(() => { $('ashot').src = '/login-screenshot?t=' + Date.now(); }, 900);
}
$('ashot').addEventListener('click', e => {
  const img = e.currentTarget, r = img.getBoundingClientRect();
  // coordonnées ramenées à la taille réelle de la capture (1280×800)
  assistAction({click: [(e.clientX - r.left) * img.naturalWidth / r.width,
                        (e.clientY - r.top) * img.naturalHeight / r.height]});
});
function typeText(){
  const t = $('atext').value;
  if (t){ assistAction({type: t}); $('atext').value = ''; }
}
$('atype').addEventListener('click', typeText);
$('atext').addEventListener('keydown', e => {
  if (e.key === 'Enter'){ e.preventDefault(); const t = $('atext').value; typeText();
                          setTimeout(() => assistAction({key: 'Enter'}), t ? 400 : 0); }
});
$('aenter').addEventListener('click', () => assistAction({key: 'Enter'}));
$('aback').addEventListener('click', () => assistAction({key: 'Backspace'}));

// --- Suivi des installations (interrogation régulière du serveur) ---
let timer = null;
async function poll(now){
  clearTimeout(timer);
  let busy = false;
  try {
    const st = await (await fetch('/jobs')).json();
    busy = renderJobs(st.jobs);
    renderCookies(st.cookies);
    busy = busy || ['running', 'assist'].includes(st.cookies.auto.state);
    await Promise.all(Object.keys(logs).map(pullLog));
  } catch(e){}
  timer = setTimeout(poll, busy ? 1000 : 4000);
}

clearBtn.addEventListener('click', async () => {
  await post('/remove', {job: 'finished'}).catch(() => {});
  poll(true);
});

btn.addEventListener('click', async () => {
  const urls = findUrls(ta.value);
  if (!urls.length){ alert('Aucun lien détecté.'); return; }
  btn.disabled = true;
  try {
    const res = await post('/download', {urls});
    if (!res.ok) throw new Error(await res.text());
    const {job} = await res.json();
    ta.value = ''; count.textContent = '';
    await poll(true);
    toggleLog(job, true);   // journal ouvert pour l'installation qu'on vient de lancer
  } catch(e){ alert('Erreur : ' + e.message); }
  btn.disabled = false;
});

poll(true);
</script>
</body>
</html>"""


def give_to_owner(paths):
    """Attribue les fichiers à PUID:PGID (si définis) pour que l'hôte puisse les gérer."""
    if not PUID.isdigit():
        return
    uid = int(PUID)
    gid = int(PGID) if PGID.isdigit() else uid
    for path in paths:
        try:
            os.chown(path, uid, gid)
        except OSError:
            pass


def purge_old_zips():
    """Supprime les ZIP de plus de ZIP_TTL secondes."""
    now = time.time()
    for token, zpath in list(ZIPS.items()):
        try:
            if now - os.path.getmtime(zpath) > ZIP_TTL:
                os.remove(zpath)
                del ZIPS[token]
        except OSError:
            ZIPS.pop(token, None)


def make_zip(files):
    """Crée un zip des fichiers donnés, renvoie (token, chemin) ou (None, None)."""
    purge_old_zips()
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


def to_netscape(text):
    """Normalise un export de cookies au format Netscape attendu par yt-dlp.

    Accepte le format Netscape (tabulations, ou espaces si copié-collé) et le JSON
    des extensions navigateur. Renvoie (texte, None) ou (None, message d'erreur).
    """
    stripped = text.strip()
    if stripped.startswith(("[", "{")):
        try:
            items = json.loads(stripped)
        except ValueError:
            return None, "JSON illisible : exporte plutôt au format Netscape (cookies.txt)"
        if isinstance(items, dict):
            items = items.get("cookies", [])
        lines = []
        for c in items if isinstance(items, list) else []:
            if not isinstance(c, dict) or not c.get("name") or not c.get("domain"):
                continue
            domain = c["domain"]
            host_only = c.get("hostOnly", not domain.startswith("."))
            lines.append("\t".join([
                ("#HttpOnly_" if c.get("httpOnly") else "") + domain,
                "FALSE" if host_only else "TRUE",
                c.get("path") or "/",
                "TRUE" if c.get("secure") else "FALSE",
                str(int(c.get("expirationDate") or 0)),
                c["name"],
                str(c.get("value", "")),
            ]))
        text = "\n".join(lines)

    rows = []
    for l in text.splitlines():
        l = l.strip("\r")
        if not l or (l.startswith("#") and not l.startswith("#HttpOnly_")):
            continue  # commentaires / en-tête
        fields = l.split("\t")
        if len(fields) != 7 and len(l.split()) == 7:
            fields = l.split()  # tabulations transformées en espaces par un éditeur
        if len(fields) == 7:
            rows.append(fields)
    if not rows:
        return None, "Format non reconnu : il faut un cookies.txt (Netscape) ou un export JSON"
    yt = [r for r in rows if "youtube.com" in r[0]]
    if not yt:
        return None, (f"Aucun cookie youtube.com dans le fichier ({len(rows)} cookie(s) "
                      "d'autres sites) : exporte depuis un onglet youtube.com")
    body = "\n".join("\t".join(r) for r in rows)
    return "# Netscape HTTP Cookie File\n" + body + "\n", None


def list_mp3():
    return {os.path.join(DEST, f) for f in os.listdir(DEST) if f.lower().endswith(".mp3")}


def now_str(ts=None):
    return datetime.datetime.fromtimestamp(ts or time.time()).strftime("%d/%m/%Y %H:%M")


# --- Connexion automatique au compte Google -----------------------------------

def cookies_age():
    try:
        return time.time() - os.path.getmtime(COOKIES_FILE)
    except OSError:
        return float("inf")


def mask_email(email):
    user, _, domain = email.partition("@")
    return (user[:2] + "***@" + domain) if domain else email


def refresh_cookies(max_age, log=None, force=False):
    """Se connecte au compte Google (ytlogin.py) et réécrit COOKIES_FILE.

    Ne fait rien si les cookies ont moins de max_age secondes (une autre installation
    vient peut-être de les rafraîchir). Après un échec, pas de nouvel essai automatique
    pendant LOGIN_BACKOFF (évite de faire bloquer le compte), sauf si force.
    Renvoie True si des cookies frais sont disponibles.
    """
    global LOGIN_PROC
    if not AUTO_LOGIN:
        return False
    log = log or (lambda msg: None)
    with LOGIN_LOCK:
        if cookies_age() < max_age:
            return True
        if not force and time.time() - LOGIN["failed_at"] < LOGIN_BACKOFF:
            log(f"🔑 Connexion automatique en pause après un échec : {LOGIN['message']}")
            return False
        LOGIN.update(state="running", message="Démarrage...", last_try=now_str())
        log("🔑 Connexion au compte YouTube pour rafraîchir les cookies...")
        ok, msg = False, "Échec inconnu"
        try:
            proc = LOGIN_PROC = subprocess.Popen(
                [sys.executable, LOGIN_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
                env={**os.environ, "LOGIN_ASSIST": "1", "COOKIES_FILE": COOKIES_FILE},
            )
            killer = threading.Timer(LOGIN_TIMEOUT, lambda: os.killpg(proc.pid, signal.SIGKILL))
            killer.start()
            for out_line in proc.stdout:
                out_line = out_line.strip()
                if out_line.startswith("##STEP##"):
                    LOGIN.update(state="running", message=out_line[8:].strip())
                    log("🔑 " + LOGIN["message"])
                elif out_line.startswith("##ASSIST##"):
                    LOGIN.update(state="assist", message=out_line[10:].strip())
                    log(f"🙋 {LOGIN['message']} : termine la vérification dans le panneau "
                        "🍪 Cookies YouTube de la page")
                    print(f"  🙋 Connexion auto : {LOGIN['message']} (assistance demandée)", flush=True)
                elif out_line.startswith("##OK##"):
                    ok, msg = True, f"Cookies récupérés ({out_line[6:].strip()} cookies)"
                elif out_line.startswith("##ERR##"):
                    msg = out_line[7:].strip()
                elif out_line:
                    print(f"  [ytlogin] {out_line}", flush=True)  # traces Playwright
            proc.wait()
            killer.cancel()
            if proc.returncode != 0:
                ok = False
                if proc.returncode < 0:
                    msg = f"Délai dépassé ({LOGIN_TIMEOUT} s)"
        except Exception as e:
            msg = f"{type(e).__name__} : {e}"
        LOGIN_PROC = None
        if ok:
            LOGIN.update(state="ok", message=msg, last_ok=now_str(), failed_at=0.0)
            log("✅ " + msg)
        else:
            LOGIN.update(state="error", message=msg, failed_at=time.time())
            log("❌ Connexion automatique impossible : " + msg)
        print(f"  🔑 Connexion auto : {msg}", flush=True)
        return ok


def cookies_refresher():
    """Tâche de fond : garde des cookies de moins de COOKIES_REFRESH heures."""
    while True:
        try:
            refresh_cookies(COOKIES_REFRESH)
        except Exception as e:
            print(f"  ⚠️  Rafraîchissement des cookies : {e}", flush=True)
        time.sleep(300)


def cookies_status():
    present = os.path.isfile(COOKIES_FILE)
    return {
        "present": present,
        "updated": now_str(os.path.getmtime(COOKIES_FILE)) if present else "",
        "password_required": bool(COOKIES_PASSWORD),
        "auto": {
            "enabled": AUTO_LOGIN,
            "account": mask_email(GOOGLE_EMAIL),
            "state": LOGIN["state"],
            "message": LOGIN["message"],
            "last_ok": LOGIN["last_ok"],
            "screenshot": AUTO_LOGIN and LOGIN["state"] != "assist" and os.path.isfile(LOGIN_SCREENSHOT),
        },
    }


# --- Installations en arrière-plan ---------------------------------------------

class Job:
    """Une installation : tourne dans son propre thread, indépendamment de la page."""

    def __init__(self, urls):
        self.id = uuid.uuid4().hex[:12]
        self.urls = urls
        self.status = "queued"      # queued -> running -> done | stopped | error
        self.created = time.time()
        self.finished = None
        self.total = len(urls)      # au minimum le nombre de liens ; ajusté si playlist
        self.produced = set()       # chemins mp3 de cette installation
        self.title = ""             # nom du morceau en cours
        self.pct = 0                # % de téléchargement du morceau en cours
        self.error = ""
        self.zip_token = None
        self.proc = None
        self.stopped = False
        self.log = []
        self.log_offset = 0         # lignes les plus anciennes supprimées (LOG_MAX)

    def add_log(self, text):
        self.log.append(text)
        if len(self.log) > LOG_MAX:
            drop = len(self.log) - LOG_MAX
            del self.log[:drop]
            self.log_offset += drop

    def log_since(self, since):
        start = max(0, since - self.log_offset)
        return self.log[start:], self.log_offset + len(self.log)

    def stop(self):
        self.stopped = True
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)  # yt-dlp et ffmpeg
            except ProcessLookupError:
                pass

    def summary(self):
        zpath = ZIPS.get(self.zip_token)
        return {
            "id": self.id,
            "status": self.status,
            "label": self.urls[0],
            "links": len(self.urls),
            "done": len(self.produced),
            "total": max(self.total, len(self.produced)),
            "title": os.path.splitext(os.path.basename(self.title))[0],
            "pct": int(self.pct),
            "error": self.error,
            "stopping": self.stopped and self.status in ("queued", "running"),
            "zip": self.zip_token if zpath and os.path.isfile(zpath) else None,
            "created": self.created,
            "finished": self.finished,
        }

    def run(self):
        try:
            with RUN_SLOTS:                     # file d'attente : MAX_PARALLEL à la fois
                if self.stopped:
                    self.status = "stopped"
                    return
                self.status = "running"
                self.execute()
        except Exception as e:
            self.status = "error"
            self.error = f"Erreur interne : {e}"
            self.add_log("❌ " + self.error)
        finally:
            self.finished = time.time()
            self.proc = None

    def execute(self):
        os.makedirs(DEST, exist_ok=True)
        before = list_mp3()     # photo du dossier AVANT, pour détecter les nouveaux fichiers

        if AUTO_LOGIN and cookies_age() > COOKIES_REFRESH:
            self.title = "🔑 Connexion à YouTube..."
            refresh_cookies(COOKIES_REFRESH, log=self.add_log)
            self.title = ""

        rc, blocked = self.run_ytdlp()
        if blocked and AUTO_LOGIN and not self.stopped:
            self.add_log("🔑 YouTube demande une connexion : reconnexion automatique puis nouvel essai")
            self.title = "🔑 Connexion à YouTube..."
            if refresh_cookies(120, log=self.add_log) and not self.stopped:
                rc, blocked = self.run_ytdlp()

        # Fichiers de l'installation = repérés dans la sortie + nouveaux fichiers du dossier
        self.produced |= (list_mp3() - before)
        give_to_owner(self.produced)
        self.title, self.pct = "", 0

        token, _ = make_zip(sorted(self.produced))
        self.zip_token = token
        if token:
            self.add_log(f"📦 ZIP prêt ({len(self.produced)} fichier(s))")
        else:
            self.add_log("Aucun nouveau fichier à zipper.")

        if self.stopped:
            self.status = "stopped"
            self.add_log("⏹ Arrêté. Les morceaux terminés sont dans le ZIP.")
        elif rc != 0 and not self.produced:
            self.status = "error"
            self.error = ("YouTube demande une connexion : cookies manquants ou expirés"
                          if blocked else "Échec du téléchargement (voir le journal)")
        else:
            self.status = "done"
            self.add_log("✅ Terminé. Fichiers dans le dossier download.")

    def run_ytdlp(self):
        """Lance yt-dlp et suit sa sortie. Renvoie (code retour, bloqué par YouTube ?)."""
        cmd = ["yt-dlp"] + YTDLP_FLAGS
        cookies_copy = None
        if os.path.isfile(COOKIES_FILE):
            if AUTO_LOGIN:
                # yt-dlp réécrit son fichier de cookies en sortant : une copie évite
                # d'écraser des cookies rafraîchis entre-temps par la connexion auto
                fd, cookies_copy = tempfile.mkstemp(prefix="cookies_", suffix=".txt")
                os.close(fd)
                shutil.copyfile(COOKIES_FILE, cookies_copy)
                cmd += ["--cookies", cookies_copy]
            else:
                cmd += ["--cookies", COOKIES_FILE]
            self.add_log("🍪 Cookies utilisés")
        else:
            self.add_log("⚠️ Aucun cookies : YouTube risque de bloquer (envoie un cookies.txt en bas de la page)")
        cmd += self.urls

        blocked = False
        try:
            self.proc = proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                start_new_session=True,  # groupe de processus : Stopper tue aussi ffmpeg
            )
            if self.stopped:            # Stopper cliqué pendant le démarrage
                self.stop()
            for out_line in iter(proc.stdout.readline, ""):
                out_line = out_line.rstrip("\n")

                # Playlist : "Downloading item N of M" -> total = M
                mi = ITEM_RE.search(out_line)
                if mi:
                    self.total = max(self.total, int(mi.group(2)))

                # Nouveau morceau en cours de téléchargement
                md = DLDEST_RE.search(out_line)
                if md and not md.group(1).endswith(".mp3"):
                    self.title = md.group(1)
                    self.pct = 0

                # % de téléchargement du morceau en cours
                mp = PCT_RE.search(out_line)
                if mp:
                    self.pct = float(mp.group(1))
                    continue  # ne pas polluer le journal avec les lignes de %

                # Morceau terminé (converti en mp3, ou déjà présent)
                mfin = DEST_RE.search(out_line) or ALREADY_RE.search(out_line)
                if mfin:
                    self.produced.add(mfin.group(1))
                    self.pct = 100

                if BOT_RE.search(out_line):
                    blocked = True
                self.add_log(out_line)
            proc.wait()
            proc.stdout.close()
            return proc.returncode, blocked
        finally:
            if cookies_copy:
                try:
                    os.remove(cookies_copy)
                except OSError:
                    pass


def start_job(urls):
    job = Job(urls)
    with JOBS_LOCK:
        purge_old_jobs()
        JOBS[job.id] = job
    threading.Thread(target=job.run, daemon=True).start()
    return job


def purge_old_jobs():
    """Oublie les installations terminées depuis plus de JOB_TTL (et au-delà de JOB_MAX)."""
    now = time.time()
    finished = sorted((j for j in JOBS.values() if j.finished), key=lambda j: j.finished)
    for i, j in enumerate(finished):
        if now - j.finished > JOB_TTL or len(finished) - i > JOB_MAX:
            JOBS.pop(j.id, None)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence les logs par requête

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/jobs":
            with JOBS_LOCK:
                jobs = sorted(JOBS.values(), key=lambda j: j.created, reverse=True)
            self.send_json({"jobs": [j.summary() for j in jobs], "cookies": cookies_status()})
        elif parsed.path == "/job-log":
            job = JOBS.get((qs.get("id") or [""])[0])
            if not job:
                self.send_error(404, "installation introuvable")
                return
            try:
                since = int((qs.get("since") or ["0"])[0])
            except ValueError:
                since = 0
            lines, nxt = job.log_since(since)
            self.send_json({"lines": lines, "next": nxt})
        elif parsed.path == "/cookies-status":
            self.send_json(cookies_status())
        elif parsed.path == "/login-screenshot":
            if not AUTO_LOGIN or not os.path.isfile(LOGIN_SCREENSHOT):
                self.send_error(404)
                return
            with open(LOGIN_SCREENSHOT, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/get-zip":
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

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, limit):
        """Lit le corps de la requête (Content-Length ou chunked via proxy). None si > limit."""
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            data = b""
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass  # trailers éventuels
                    return data
                data += self.rfile.read(size)
                self.rfile.readline()  # CRLF de fin de chunk
                if len(data) > limit:
                    return None
        length = int(self.headers.get("Content-Length", 0))
        if length > limit:
            return None
        return self.rfile.read(length) if length > 0 else b""

    def read_json(self, limit=65536):
        try:
            data = json.loads(self.read_body(limit) or b"{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def password_ok(self):
        """Mot de passe COOKIES_PASSWORD (si défini) pour toucher aux cookies."""
        if not COOKIES_PASSWORD:
            return True
        given = self.headers.get("X-Cookies-Password", "")
        return hmac.compare_digest(given.encode("utf-8"), COOKIES_PASSWORD.encode("utf-8"))

    def upload_cookies(self):
        """Reçoit un cookies.txt (Netscape ou JSON) depuis la page et le remplace sur le disque."""
        if not self.password_ok():
            self.send_text(403, "Mot de passe incorrect")
            return
        data = self.read_body(COOKIES_MAX_SIZE)
        if data is None:
            self.send_text(400, "Fichier trop gros (max 3 Mo) : exporte seulement les cookies de youtube.com")
            return
        if not data:
            self.send_text(400, "Fichier vide")
            return
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            self.send_text(400, "Ce n'est pas un fichier texte")
            return
        text, err = to_netscape(text)
        if err:
            print(f"  ⚠️  Cookies refusés : {err}", flush=True)
            self.send_text(400, err)
            return
        os.makedirs(os.path.dirname(COOKIES_FILE) or ".", exist_ok=True)
        tmp = COOKIES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, COOKIES_FILE)
        print("  🍪 Cookies mis à jour depuis la page", flush=True)
        self.send_text(200, "✅ Cookies enregistrés")

    def refresh_now(self):
        """Bouton « Reconnecter maintenant » : connexion Google immédiate, en arrière-plan."""
        if not AUTO_LOGIN:
            self.send_text(400, "Connexion automatique non configurée (GOOGLE_EMAIL / GOOGLE_PASSWORD)")
            return
        if not self.password_ok():
            self.send_text(403, "Mot de passe incorrect")
            return
        if LOGIN["state"] not in ("running", "assist"):
            threading.Thread(target=refresh_cookies, args=(0,), kwargs={"force": True},
                             daemon=True).start()
        self.send_text(202, "Connexion lancée")

    def login_input(self):
        """Mode assistance : transmet un clic / texte / touche au navigateur de connexion."""
        if not self.password_ok():
            self.send_text(403, "Mot de passe incorrect")
            return
        data = self.read_json(4096)
        action = None
        if isinstance(data.get("click"), list) and len(data["click"]) == 2:
            try:
                action = {"click": [float(data["click"][0]), float(data["click"][1])]}
            except (TypeError, ValueError):
                pass
        elif isinstance(data.get("type"), str):
            action = {"type": data["type"][:200]}
        elif data.get("key") in ("Enter", "Backspace", "Tab", "Escape"):
            action = {"key": data["key"]}
        proc = LOGIN_PROC
        if not action or LOGIN["state"] != "assist" or not proc or proc.poll() is not None:
            self.send_text(409, "Aucune vérification en attente")
            return
        try:
            proc.stdin.write(json.dumps(action) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.send_text(409, "Connexion terminée")
            return
        self.send_text(200, "OK")

    def stop_job(self):
        """Bouton Stopper : tue yt-dlp (et ffmpeg) de l'installation donnée."""
        job = JOBS.get(str(self.read_json(4096).get("job", "")))
        if not job or job.status not in ("queued", "running"):
            self.send_text(404, "Aucune installation en cours")
            return
        job.stop()
        self.send_text(200, "Arrêt demandé")

    def remove_job(self):
        """Retire une installation terminée de la liste (« finished » = toutes les terminées)."""
        target = str(self.read_json(4096).get("job", ""))
        with JOBS_LOCK:
            for job in list(JOBS.values()):
                if job.finished and target in (job.id, "finished"):
                    del JOBS[job.id]
        self.send_text(200, "OK")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/cookies":
            self.upload_cookies()
        elif path == "/cookies-refresh":
            self.refresh_now()
        elif path == "/login-input":
            self.login_input()
        elif path == "/stop":
            self.stop_job()
        elif path == "/remove":
            self.remove_job()
        elif path == "/download":
            urls = self.read_json().get("urls", [])
            # Filtre de sécurité : on ne garde que de vraies URLs
            urls = [u.strip() for u in urls if isinstance(u, str) and URL_RE.fullmatch(u.strip())]
            if not urls:
                self.send_text(400, "Aucun lien valide")
                return
            job = start_job(urls)
            print(f"  ▶️  Installation {job.id} : {len(urls)} lien(s)", flush=True)
            self.send_json({"job": job.id})
        else:
            self.send_error(404)


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


def start_auto_login():
    """Connexion automatique : vérifie Playwright puis lance le rafraîchissement périodique."""
    if not AUTO_LOGIN:
        return
    if importlib.util.find_spec("camoufox") is None and importlib.util.find_spec("playwright") is None:
        LOGIN.update(state="error", failed_at=float("inf"),
                     message="Camoufox non installé (pip install camoufox && python3 -m camoufox fetch)")
        print(f"  ⚠️  {LOGIN['message']}", flush=True)
        return
    LOGIN.update(state="idle", message="En attente")
    print(f"  🔑 Connexion automatique activée pour {mask_email(GOOGLE_EMAIL)} "
          f"(cookies rafraîchis toutes les {COOKIES_REFRESH / 3600:g} h)", flush=True)
    threading.Thread(target=cookies_refresher, daemon=True).start()


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
    give_to_owner([DEST])
    install_cookies_from_env()
    start_auto_login()
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
