#!/usr/bin/env python3
"""
🍺 Wiesn Reservierungsportal Monitor
Überwacht Reservierungsportale auf neue Tisch-Verfügbarkeiten (Dropdowns)
"""

import asyncio
import json
import os
import hashlib
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from playwright.async_api import async_playwright

# ─────────────────────────────────────────────────────────────
# KONFIGURATION – Entweder hier direkt oder per .env / Umgebungsvariablen
# ─────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Zu überwachende URLs ──────────────────────────────────────
URLS = [
    "https://reservierung.derhimmelderbayern.de/reservierung",       # Himmel der Bayern
    "https://reservierung.hb-festzelt.de/reservierung",              # Hofbräu-Festzelt
    "https://reservierung.armbrustschuetzenzelt.de/reservierung",    # Armbrustschützenzelt
    "https://www.festhalle-augustiner.com/reservierung/",            # Festhalle Augustiner
    "https://reservierung.braeurosl.de/reservation/",                # Bräurosl
    "https://reservierung.fischer-vroni.de/reservation",             # Fischer-Vroni
    "https://reservierung.loewenbraeuzelt.de/reservierung",          # Löwenbräuzelt
    "https://reservierung.ochsenbraterei.de/reservierungen",         # Ochsenbraterei
    "https://reservierung.festhalle-schottenhamel.de/reservation/",  # Schottenhamel
    "https://reservierung.schuetzenfestzelt.com/reservation/",       # Schützenfestzelt
    "https://reservierung.paulanerfestzelt.de/reservierung",         # Paulaner Festzelt
]

# ── Schlüsselwörter, die eine Benachrichtigung auslösen ───────
# Wenn neue Dropdown-Optionen diese Wörter enthalten, bist du sofort dabei.
RELEVANT_KEYWORDS = [
    "Freitag", "Samstag", "Donnerstag", "Mittwoch", "Dienstag", "Montag", "Sonntag",
    "Abend", "abend", "Abends", "abends", "Nachmittags", "Nachmittag", "nachmittags", "nachmittag", "15:", "16:", "17:", "18:", "19:", "20:", "21:", "22:", "23:",
    "available", "verfügbar",
]

# ── E-Mail (optional) ─────────────────────────────────────────
EMAIL_ENABLED   = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
EMAIL_USER      = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD  = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")

# ── Allgemein ─────────────────────────────────────────────────
STATE_FILE             = os.getenv("STATE_FILE", "state.json")
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))
HEADLESS               = os.getenv("HEADLESS", "true").lower() == "true"

# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("wiesn-monitor")


# ─────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────

async def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram nicht konfiguriert (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID fehlen)")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            resp.raise_for_status()
            log.info("Telegram-Nachricht gesendet ✓")
            return True
    except Exception as e:
        log.error(f"Telegram-Fehler: {e}")
        return False


def send_email(subject: str, body: str) -> bool:
    if not EMAIL_ENABLED:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_USER
        msg["To"]      = EMAIL_RECIPIENT
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USER, EMAIL_RECIPIENT, msg.as_string())
        log.info("E-Mail gesendet ✓")
        return True
    except Exception as e:
        log.error(f"E-Mail-Fehler: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# PAGE EXTRACTION
# ─────────────────────────────────────────────────────────────

async def extract_page_state(page, url: str) -> dict | None:
    """
    Lädt die Seite mit Playwright und extrahiert alle Dropdown-Optionen
    sowie relevante Schaltflächen und sichtbaren Text.
    """
    try:
        await page.goto(url, wait_until="networkidle", timeout=40_000)
        # Extra-Wartezeit für langsame JS-Frameworks
        await page.wait_for_timeout(3_000)

        state = await page.evaluate("""
        () => {
            const result = { dropdowns: {}, buttons: [], visible_text: '' };

            // ── Native <select> Elemente ─────────────────────────────
            document.querySelectorAll('select').forEach((sel, i) => {
                const key = sel.name || sel.id
                          || sel.getAttribute('aria-label')
                          || sel.closest('label')?.textContent?.trim()
                          || `select_${i}`;
                result.dropdowns[key] = Array.from(sel.options).map(o => ({
                    value:    o.value,
                    text:     o.text.trim(),
                    disabled: o.disabled || o.hidden,
                    selected: o.selected,
                })).filter(o => o.text !== '');
            });

            // ── Custom / div-basierte Dropdowns (z.B. Select2, Vue Select) ──
            const customItems = document.querySelectorAll(
                '[role="option"], [role="listbox"] *, .dropdown-item, ' +
                '.select-option, .v-select__item, li[data-value]'
            );
            if (customItems.length > 0) {
                result.dropdowns['__custom__'] = Array.from(customItems).map(el => ({
                    text:     el.textContent?.trim() || '',
                    disabled: el.getAttribute('aria-disabled') === 'true'
                              || el.classList.contains('disabled'),
                })).filter(o => o.text !== '');
            }

            // ── Datum-/Zeit-Schaltflächen ────────────────────────────
            result.buttons = Array.from(
                document.querySelectorAll('button, [role="button"], .btn')
            ).map(b => b.textContent?.trim()).filter(t => t && t.length < 120);

            // ── Sichtbarer Seitentext (für Fallback) ─────────────────
            result.visible_text = (document.body?.innerText || '').substring(0, 8_000);

            return result;
        }
        """)
        return state

    except Exception as e:
        log.error(f"Fehler beim Laden von {url}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# STATE MANAGEMENT
# ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def url_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:10]


# ─────────────────────────────────────────────────────────────
# CHANGE DETECTION
# ─────────────────────────────────────────────────────────────

def is_relevant(text: str) -> bool:
    return any(kw.lower() in text.lower() for kw in RELEVANT_KEYWORDS)


def find_changes(old: dict, new: dict) -> list[str]:
    """
    Vergleicht alten und neuen State, gibt eine Liste von Änderungs-Strings zurück.
    Relevante Änderungen werden mit 🚨 markiert, sonstige mit ➕/➖.
    """
    changes = []

    old_dd = old.get("dropdowns", {})
    new_dd = new.get("dropdowns", {})

    # Alle Dropdown-Schlüssel (alt + neu)
    all_keys = set(old_dd) | set(new_dd)

    for key in all_keys:
        old_opts = {o["text"]: o for o in old_dd.get(key, [])}
        new_opts = {o["text"]: o for o in new_dd.get(key, [])}

        added   = set(new_opts) - set(old_opts)
        removed = set(old_opts) - set(new_opts)

        # Optionen, die von "disabled" auf "enabled" wechseln
        newly_enabled = {
            t for t in (set(old_opts) & set(new_opts))
            if old_opts[t].get("disabled") and not new_opts[t].get("disabled")
        }
        newly_disabled = {
            t for t in (set(old_opts) & set(new_opts))
            if not old_opts[t].get("disabled") and new_opts[t].get("disabled")
        }

        for text in added:
            icon = "🚨" if is_relevant(text) else "➕"
            label = "NEU verfügbar" if is_relevant(text) else "Neue Option"
            changes.append(f'{icon} {label} [{key}]: <b>{text}</b>')

        for text in newly_enabled:
            icon = "🚨" if is_relevant(text) else "🔓"
            changes.append(f'{icon} Jetzt buchbar [{key}]: <b>{text}</b>')

        for text in removed:
            if is_relevant(text):
                changes.append(f'❌ Entfernt [{key}]: {text}')

        for text in newly_disabled:
            if is_relevant(text):
                changes.append(f'🔒 Nicht mehr buchbar [{key}]: {text}')

    # Neue relevante Buttons
    old_btns = set(old.get("buttons", []))
    new_btns = set(new.get("buttons", []))
    for btn in (new_btns - old_btns):
        if is_relevant(btn):
            changes.append(f'🔘 Neuer Button: <b>{btn}</b>')

    return changes


# ─────────────────────────────────────────────────────────────
# MAIN CHECK LOGIC
# ─────────────────────────────────────────────────────────────

async def check_url(browser, url: str, saved_states: dict):
    page = await browser.new_page(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    )
    try:
        log.info(f"Prüfe: {url}")
        new_state = await extract_page_state(page, url)
        if new_state is None:
            return

        key = url_key(url)
        old_state = saved_states.get(key)

        if old_state is None:
            # Erster Lauf: Zustand speichern, keine Benachrichtigung
            dd_count = sum(len(v) for v in new_state["dropdowns"].values())
            log.info(f"  Initialzustand gespeichert ({dd_count} Dropdown-Optionen erkannt)")
            saved_states[key] = new_state
            return

        changes = find_changes(old_state, new_state)
        relevant = [c for c in changes if c.startswith(("🚨", "🔓"))]

        if changes:
            now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            prio = "RELEVANT – JETZT BUCHEN!" if relevant else "Sonstige Änderung"

            tg_msg = (
                f"🍺 <b>Wiesn Monitor – {prio}</b>\n\n"
                f"🔗 {url}\n\n"
                + "\n".join(changes) +
                f"\n\n🕐 {now}"
            )
            email_body = (
                f"<h2>🍺 Wiesn Reservierung – {prio}</h2>"
                f"<p><a href='{url}'>{url}</a></p>"
                "<ul>" + "".join(f"<li>{c}</li>" for c in changes) + "</ul>"
                f"<p><small>{now}</small></p>"
            )

            log.info(f"  {len(changes)} Änderung(en) erkannt – sende Benachrichtigungen")
            await send_telegram(tg_msg)
            if EMAIL_ENABLED:
                send_email(f"Wiesn Monitor: {prio}", email_body)
        else:
            log.info("  Keine Änderungen")

        saved_states[key] = new_state

    finally:
        await page.close()


async def run_checks(saved_states: dict):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        for url in URLS:
            await check_url(browser, url, saved_states)
            await asyncio.sleep(3)   # kurze Pause zwischen URLs
        await browser.close()


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

async def main():
    log.info("=" * 55)
    log.info("🍺  Wiesn Reservierungsmonitor gestartet")
    log.info(f"   Überwache {len(URLS)} URL(s)")
    log.info(f"   Interval: {CHECK_INTERVAL_MINUTES} Minuten")
    log.info("=" * 55)

    await send_telegram(
        f"🍺 <b>Wiesn Monitor gestartet!</b>\n"
        f"Überwache {len(URLS)} Reservierungsportal(e).\n"
        f"Prüfintervall: alle {CHECK_INTERVAL_MINUTES} Minuten."
    )

    saved_states = load_state()

    while True:
        try:
            await run_checks(saved_states)
            save_state(saved_states)
        except Exception as e:
            log.error(f"Unerwarteter Fehler: {e}")
            await send_telegram(f"⚠️ <b>Wiesn Monitor Fehler:</b>\n{e}")

        log.info(f"Nächste Prüfung in {CHECK_INTERVAL_MINUTES} Minuten …")
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    asyncio.run(main())
