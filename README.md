# 🍺 Wiesn Reservierungsmonitor

Überwacht Reservierungsportale automatisch auf neue verfügbare Tische –
insbesondere neue Wochentage und Abend-Slots in Dropdown-Menüs.
Bei Änderungen kommt sofort eine **Telegram-Nachricht** (optional auch E-Mail).

---

## Schnellstart (lokal oder auf VPS)

### 1. Telegram-Bot einrichten

1. Öffne Telegram und schreibe `@BotFather`
2. Sende `/newbot` und folge den Anweisungen → du erhältst einen **Token**
3. Schreibe deinen neuen Bot an (irgendeine Nachricht)
4. Öffne im Browser:
   `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates`
   → kopiere die `id` aus dem `chat`-Objekt → das ist deine **Chat-ID**

### 2. Konfiguration

```bash
cp .env.example .env
# .env öffnen und Token + Chat-ID eintragen
```

Außerdem in `monitor.py` die gewünschten URLs in der `URLS`-Liste eintragen.

### 3a. Ohne Docker (lokal)

```bash
pip install -r requirements.txt
playwright install chromium
python monitor.py
```

### 3b. Mit Docker (empfohlen für Dauerbetrieb)

```bash
docker compose up -d
docker compose logs -f   # Logs verfolgen
```

---

## Deployment-Optionen

### Option A: Eigener Server / VPS (€3–5/Monat)
Empfehlung: **Hetzner Cloud CX11** oder **Oracle Cloud Free Tier**

```bash
# Server einrichten
apt update && apt install -y docker.io docker-compose-plugin
# Repo klonen, .env befüllen
git clone <dein-repo>
cd wiesn-monitor
cp .env.example .env && nano .env
docker compose up -d
```

### Option B: GitHub Actions (kostenlos)
Der Monitor läuft alle 5 Minuten als GitHub Action.
Der State (welche Optionen zuletzt gesehen) wird als Cache gespeichert.

1. Repository auf GitHub anlegen und Dateien hochladen
2. Unter **Settings → Secrets and variables → Actions** eintragen:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. Actions-Tab → Workflow aktivieren → fertig!

### Option C: Raspberry Pi / lokaler Rechner
```bash
# Cron-Job einrichten (alle 5 Minuten)
crontab -e
# Folgende Zeile einfügen:
*/5 * * * * cd /pfad/zum/ordner && python monitor_once.py >> monitor.log 2>&1
```

---

## Weitere URLs hinzufügen

In `monitor.py` einfach in die `URLS`-Liste eintragen:

```python
URLS = [
    "https://reservierung.derhimmelderbayern.de/reservierung",
    "https://www.hofbraeuhaus.de/de/reservierung.html",
    "https://...",
]
```

---

## E-Mail aktivieren (optional)

In `.env` setzen:
```
EMAIL_ENABLED=true
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USER=deine@gmail.com
EMAIL_PASSWORD=dein-google-app-passwort   # Kein normales Passwort!
EMAIL_RECIPIENT=benachrichtigung@example.com
```

> **Hinweis Gmail:** Unter Sicherheitseinstellungen ein "App-Passwort" erstellen
> (2-Faktor muss aktiviert sein).

---

## Wie funktioniert die Erkennung?

Der Monitor nutzt **Playwright** (Headless Chrome) um die Seiten zu rendern –
das ist nötig, weil Reservierungsportale meist JavaScript-Dropdowns verwenden.

Bei jedem Check:
1. Seite wird vollständig geladen (inkl. JS-Ausführung)
2. Alle `<select>`-Elemente und custom Dropdowns werden ausgelesen
3. Optionen werden mit dem letzten Stand verglichen
4. Neue Optionen, die **Freitag / Samstag / Abend / 19: / 20:…** enthalten → 🚨 Alert!
5. Auch: Optionen die von `disabled` auf `enabled` wechseln

---

## Troubleshooting

**Keine Dropdowns gefunden?**
Manche Portale laden Optionen erst nach Interaktion (z.B. erst nach Klick auf ein Datum).
→ Issue melden, dann kann ein Klick-Schritt ergänzt werden.

**False Positives?**
`RELEVANT_KEYWORDS` in `monitor.py` anpassen.

**Telegram-Test:**
```bash
python -c "
import asyncio, monitor
asyncio.run(monitor.send_telegram('🧪 Test erfolgreich!'))
"
```
