#!/usr/bin/env python3
"""
Connexion automatique à un compte Google/YouTube et export des cookies pour yt-dlp.

Lancé par app.py (ou à la main :  python3 ytlogin.py). Variables d'environnement :
  GOOGLE_EMAIL, GOOGLE_PASSWORD   identifiants du compte (obligatoires)
  GOOGLE_TOTP_SECRET              secret de l'application d'authentification (2FA, optionnel)
  COOKIES_FILE                    fichier cookies.txt à écrire
  BROWSER_PROFILE                 profil du navigateur conservé entre deux connexions
  LOGIN_ASSIST=1                  mode assistance (activé par app.py, voir plus bas)

Navigateur : Camoufox (Firefox anti-détection piloté par Playwright), headless. Le
Firefox/Chromium standard de Playwright est refusé par Google (« navigateur non sécurisé »).
Un profil persistant est réutilisé : tant que la session Google est valide, aucun mot de
passe n'est retapé (moins de connexions suspectes aux yeux de Google).

Mode assistance : quand Google pose une question impossible à automatiser (numéro de
téléphone, code SMS, captcha…), le script affiche « ##ASSIST## raison », met à jour la
capture d'écran chaque seconde et exécute les actions reçues sur stdin, une par ligne en
JSON : {"click": [x, y]}, {"type": "texte"} ou {"key": "Enter"}. La page web s'en sert
pour qu'on termine la vérification à la main. Google ne la redemande normalement pas
ensuite, puisque le profil du navigateur est conservé.

Sortie : lignes « ##STEP## message » (progression) puis « ##OK## n » ou « ##ERR## message ».
"""
import base64
import contextlib
import hashlib
import hmac
import json
import os
import queue
import re
import struct
import sys
import threading
import time
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
EMAIL = os.environ.get("GOOGLE_EMAIL", "").strip()
PASSWORD = os.environ.get("GOOGLE_PASSWORD", "")
TOTP_SECRET = os.environ.get("GOOGLE_TOTP_SECRET", "").replace(" ", "").upper()
COOKIES_FILE = os.environ.get("COOKIES_FILE") or os.path.join(HERE, "cookies.txt")
CONFIG_DIR = os.path.dirname(COOKIES_FILE) or "."
PROFILE = os.environ.get("BROWSER_PROFILE") or os.path.join(CONFIG_DIR, "browser-profile")
SCREENSHOT = os.path.join(CONFIG_DIR, "login-debug.png")
TIMEOUT = 180  # secondes pour boucler la connexion (validation sur téléphone comprise)
ASSIST = os.environ.get("LOGIN_ASSIST") == "1"
ASSIST_TIMEOUT = 600  # secondes laissées pour terminer une vérification à la main
ASSIST_KEYS = {"Enter", "Backspace", "Tab", "Escape"}
STUCK_AFTER = 30      # page inconnue sans évolution pendant 30 s -> assistance

SIGNIN_URL = (
    "https://accounts.google.com/ServiceLogin?service=youtube&uilel=3&passive=true&hl=fr"
    "&continue=https%3A%2F%2Fwww.youtube.com%2Fsignin%3Faction_handle_signin%3Dtrue"
    "%26app%3Ddesktop%26hl%3Dfr%26next%3Dhttps%253A%252F%252Fwww.youtube.com%252F"
)
# Boutons « plus tard » des pages intermédiaires (options de récupération, passkeys…)
SKIP_RE = re.compile(r"^(not now|plus tard|pas maintenant|skip|ignorer|later|remind me later)$", re.I)
# Champ identifiant : #identifierId (type text depuis 2025), type=email sur les anciennes pages
EMAIL_SEL = "#identifierId, input[name=identifier], input[type=email]"
EMAIL_BAD = "#identifierId[aria-invalid=true], input[name=identifier][aria-invalid=true], input[type=email][aria-invalid=true]"
PASSWORD_SEL = "input[type=password][name=Passwd]"
CONSENT_RE = re.compile(r"(tout refuser|reject all|tout accepter|accept all)", re.I)


class LoginError(Exception):
    pass


def step(msg):
    print(f"##STEP## {msg}", flush=True)


def totp_now(secret):
    """Code à 6 chiffres de l'application d'authentification (RFC 6238)."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1000000:06d}"


def visible(page, selector):
    try:
        return page.locator(selector).first.is_visible()
    except Exception:
        return False


def click_button(page, pattern):
    """Clique le premier bouton (ou lien) visible dont le texte correspond."""
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=pattern)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                return True
        except Exception:
            pass
    return False


def dismiss_consent(page):
    """Bannière cookies européenne (consent.youtube.com / consent.google.com)."""
    if "consent." in urlparse(page.url).netloc or visible(page, "form[action*='consent']"):
        if click_button(page, CONSENT_RE):
            page.wait_for_load_state("domcontentloaded")


def youtube_logged_in(page):
    try:
        page.wait_for_load_state("domcontentloaded")
        dismiss_consent(page)
        page.wait_for_function("() => window.ytcfg && ytcfg.get", timeout=15000)
        return bool(page.evaluate("() => ytcfg.get('LOGGED_IN')"))
    except Exception:
        return False


def sign_in(page):
    """Déroule le formulaire Google jusqu'au retour sur youtube.com."""
    page.goto(SIGNIN_URL, wait_until="domcontentloaded")
    deadline = time.time() + TIMEOUT
    email_sent = password_sent = totp_sent = 0
    phone_notified = False
    last_url, last_change = "", time.time()

    while time.time() < deadline:
        url = page.url
        host = urlparse(url).netloc
        if host.endswith("youtube.com") and "consent." not in host:
            return
        dismiss_consent(page)

        if "/signin/rejected" in url or "signin/v2/deniedsigninrejected" in url:
            raise LoginError("Google refuse ce navigateur automatisé (« navigateur non sécurisé »)")
        if visible(page, EMAIL_BAD):
            raise LoginError("Adresse Gmail inconnue : vérifie GOOGLE_EMAIL")
        if visible(page, PASSWORD_SEL + "[aria-invalid=true]"):
            raise LoginError("Mot de passe refusé : vérifie GOOGLE_PASSWORD")
        if "/challenge/recaptcha" in url or visible(page, "iframe[src*='recaptcha'], img#captchaimg"):
            return assist(page, "Google demande un captcha")
        if "/challenge/iap" in url:
            return assist(page, "Google demande un numéro de téléphone pour confirmer ce nouvel appareil")
        if "/challenge/ipp" in url:
            return assist(page, "Google demande le code reçu par SMS")
        if "/challenge/sk" in url:
            raise LoginError("Google demande une clé de sécurité physique : impossible depuis le serveur")

        if "accountchooser" in url and EMAIL:
            loc = page.get_by_text(EMAIL, exact=False)
            if loc.count():
                loc.first.click()
                time.sleep(2)
                continue

        if visible(page, EMAIL_SEL) and email_sent < 2:
            step("Saisie de l'adresse Gmail")
            page.locator(EMAIL_SEL).first.fill(EMAIL)
            page.keyboard.press("Enter")
            email_sent += 1
            time.sleep(3)
            continue

        if visible(page, PASSWORD_SEL):
            if password_sent:
                time.sleep(1)  # le champ reste affiché le temps de la vérification
                continue
            step("Saisie du mot de passe")
            field = page.locator(PASSWORD_SEL).first
            field.fill("")
            field.press_sequentially(PASSWORD, delay=40)
            page.keyboard.press("Enter")
            password_sent += 1
            time.sleep(4)
            continue

        if "/challenge/selection" in url:
            if TOTP_SECRET and visible(page, "[data-challengetype='6']"):
                step("2FA : choix de l'application d'authentification")
                page.locator("[data-challengetype='6']").first.click()
                time.sleep(3)
                continue
            return assist(page, "Google demande de choisir une méthode de vérification")

        if "/challenge/totp" in url or visible(page, "input[name=totpPin]"):
            if not TOTP_SECRET:
                return assist(page, "Code de l'appli d'authentification demandé (ou GOOGLE_TOTP_SECRET)")
            if totp_sent >= 2:
                raise LoginError("Code 2FA refusé : vérifie GOOGLE_TOTP_SECRET (et l'heure du serveur)")
            step("2FA : saisie du code de l'application d'authentification")
            page.locator("input[name=totpPin], input[type=tel]").first.fill(totp_now(TOTP_SECRET))
            page.keyboard.press("Enter")
            totp_sent += 1
            time.sleep(4)
            continue

        if "/challenge/dp" in url or "/challenge/az" in url or "/challenge/ootp" in url:
            if not phone_notified:
                step("📱 Approuve la connexion sur ton téléphone (notification Google)")
                phone_notified = True
            time.sleep(2)
            continue

        if click_button(page, SKIP_RE):
            step("Page intermédiaire Google ignorée")
            time.sleep(2)
            continue

        # Page inconnue qui n'évolue plus : on passe la main
        if url != last_url:
            last_url, last_change = url, time.time()
        elif time.time() - last_change > STUCK_AFTER:
            return assist(page, "Page Google inattendue")
        time.sleep(1)

    return assist(page, "La connexion n'aboutit pas")


def stdin_actions():
    """Actions envoyées par la page web (une ligne JSON par action), lues en arrière-plan."""
    actions = queue.Queue()

    def reader():
        for line in sys.stdin:
            try:
                actions.put(json.loads(line))
            except ValueError:
                pass
    threading.Thread(target=reader, daemon=True).start()
    return actions


def save_screenshot(page):
    tmp = SCREENSHOT + ".tmp.png"
    try:
        page.screenshot(path=tmp)
        os.replace(tmp, SCREENSHOT)
    except Exception:
        pass


def assist(page, reason):
    """Laisse l'utilisateur terminer la vérification depuis la page web (voir docstring)."""
    if not ASSIST:
        raise LoginError(f"{reason} : impossible en automatique (voir la capture d'écran)")
    print(f"##ASSIST## {reason}", flush=True)
    actions = stdin_actions()
    deadline = time.time() + ASSIST_TIMEOUT
    while time.time() < deadline:
        host = urlparse(page.url).netloc
        if host.endswith("youtube.com") and "consent." not in host:
            step("Vérification terminée, merci !")
            return
        save_screenshot(page)
        try:
            action = actions.get(timeout=1)
        except queue.Empty:
            continue
        try:
            if "click" in action:
                x, y = (float(v) for v in action["click"][:2])
                page.mouse.click(x, y)
            elif "type" in action:
                page.keyboard.type(str(action["type"])[:200], delay=60)
            elif action.get("key") in ASSIST_KEYS:
                page.keyboard.press(action["key"])
        except Exception as e:
            print(f"action ignorée : {e}", flush=True)
        time.sleep(0.5)
        save_screenshot(page)
    raise LoginError(f"{reason} : délai d'assistance dépassé ({ASSIST_TIMEOUT // 60} min)")


def to_netscape(cookies):
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c["domain"]
        if not (domain.endswith("youtube.com") or domain.endswith("google.com")):
            continue
        expires = int(c["expires"]) if c.get("expires", -1) > 0 else 0
        lines.append("\t".join([
            ("#HttpOnly_" if c.get("httpOnly") else "") + domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            c.get("path") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(expires),
            c["name"],
            c["value"],
        ]))
    return "\n".join(lines) + "\n", len(lines) - 1


def open_browser(stack):
    """Firefox headless avec profil persistant.

    Camoufox (Firefox anti-détection) de préférence : Google refuse la connexion
    depuis le Firefox/Chromium standard de Playwright (« navigateur non sécurisé »).
    """
    os.makedirs(PROFILE, exist_ok=True)
    options = {"headless": True, "locale": "fr-FR", "viewport": {"width": 1280, "height": 800}}
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        Camoufox = None
    if Camoufox:
        return stack.enter_context(Camoufox(
            persistent_context=True, user_data_dir=PROFILE, os="linux", **options))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise LoginError("Camoufox n'est pas installé (pip install camoufox && "
                         "python3 -m camoufox fetch)")
    step("⚠️ Camoufox absent : Firefox standard (Google risque de le refuser)")
    pw = stack.enter_context(sync_playwright())
    return pw.firefox.launch_persistent_context(PROFILE, timezone_id="Europe/Paris", **options)


def main():
    if not EMAIL or not PASSWORD:
        raise LoginError("GOOGLE_EMAIL et GOOGLE_PASSWORD doivent être définis")

    with contextlib.ExitStack() as stack:
        step("Ouverture du navigateur")
        try:
            ctx = open_browser(stack)
        except LoginError:
            raise
        except Exception as e:
            print(e, flush=True)  # détail complet dans les logs du serveur
            raise LoginError("Impossible de lancer le navigateur (python3 -m camoufox fetch ?)")
        stack.callback(ctx.close)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(20000)
        try:
            step("Vérification de la session YouTube")
            page.goto("https://www.youtube.com/", wait_until="domcontentloaded")
            if not youtube_logged_in(page):
                step("Session expirée : connexion au compte Google")
                sign_in(page)
                if not youtube_logged_in(page):
                    raise LoginError("Connecté à Google mais YouTube ne reconnaît pas la session")
            # Page neutre avant export (conseil yt-dlp : évite une rotation immédiate des cookies)
            page.goto("https://www.youtube.com/robots.txt", wait_until="domcontentloaded")
            text, n = to_netscape(ctx.cookies())
        except Exception as e:
            try:
                page.screenshot(path=SCREENSHOT)
            except Exception:
                pass
            if isinstance(e, LoginError):
                raise
            raise LoginError(f"{type(e).__name__} : {str(e).splitlines()[0] if str(e) else ''}")

    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = COOKIES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, COOKIES_FILE)
    try:
        os.remove(SCREENSHOT)  # capture d'une ancienne erreur : plus d'actualité
    except OSError:
        pass
    print(f"##OK## {n}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except LoginError as e:
        print(f"##ERR## {e}", flush=True)
        sys.exit(1)
