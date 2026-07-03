# Personal Agent — Telegram Setup Konzept

## Wie es funktioniert

```
┌─────────────────────────────────────────────────────────────────┐
│                        DU (Telegram App)                        │
│                                                                 │
│        💬 Textnachricht        🎤 Sprachnachricht               │
└──────────────┬─────────────────────────┬───────────────────────┘
               │                         │
               ▼                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      TELEGRAM SERVER                            │
│                    (Bot API – kostenlos)                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │  Polling alle ~1 Sek.
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    HETZNER VPS  (~4 €/Monat)                    │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                   bot.py (läuft 24/7)                   │   │
│   │                                                         │   │
│   │   Text ──────────────────────────────┐                  │   │
│   │                                      │                  │   │
│   │   Sprache (.ogg)                     │                  │   │
│   │      │                               │                  │   │
│   │      ▼                               ▼                  │   │
│   │   Whisper STT ────────────►  Claude API (Anthropic)     │   │
│   │   (Sprache → Text)               │                      │   │
│   │                                  │ Antwort              │   │
│   │                          ┌───────┴───────┐              │   │
│   │                          │               │              │   │
│   │                          ▼               ▼              │   │
│   │                     📝 Text         🔊 Sprache          │   │
│   │                                    (TTS optional)       │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   ┌──────────────┐   ┌─────────────────────────────────────┐   │
│   │  Gedächtnis  │   │        profiles/marc.txt            │   │
│   │  (SQLite)    │   │   (Persönlichkeit, Kontext, Ziele)  │   │
│   └──────────────┘   └─────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                        DU (Telegram App)                        │
│                                                                 │
│        💬 Textantwort          🎤 Sprachantwort                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Komponenten

### Hosting: Hetzner VPS
- **Modell**: CX22 (~4 €/Monat, Festpreis)
- **Standort**: Deutschland (Nürnberg oder Falkenstein)
- **Kosten**: Fix — egal wie oft du den Bot nutzt
- **Rating**: Sehr gut bewertet, einer der zuverlässigsten Hoster in Europa
- **Datenschutz**: Server in Deutschland, DSGVO-konform

### Telegram Bot
- Kostenlos via [@BotFather](https://t.me/BotFather)
- Empfängt Text- und Sprachnachrichten
- Sendet Text zurück (und optional Sprachnoten)
- Library: `python-telegram-bot`

### Sprache → Text (STT)
- **Option A**: OpenAI Whisper API (~0.006$/Minute — sehr günstig)
- **Option B**: Whisper lokal auf dem VPS (kostenlos, etwas langsamer)

### Claude (Anthropic API)
- Verarbeitet Nachrichten mit persönlichem Kontext
- Kennt dein Profil, deine Ziele, vergangene Gespräche
- Antwortet als persönlicher Assistent / Freund / Sparringspartner

### Text → Sprache (TTS) — optional
- **Option A**: OpenAI TTS (~0.015$/1000 Zeichen)
- **Option B**: gTTS (Google, kostenlos, einfachere Stimme)
- **Option C**: ElevenLabs (beste Qualität, kostenloser Tier vorhanden)

### Gedächtnis
- Gesprächsverlauf in SQLite gespeichert
- Kontext bleibt über mehrere Tage/Wochen erhalten
- Profildatei (`profiles/marc.txt`) gibt dem Agent Persönlichkeit

---

## Geschätzte monatliche Kosten

| Komponente         | Kosten          |
|--------------------|-----------------|
| Hetzner CX22       | ~4 €/Monat      |
| Anthropic API      | ~2–5 €/Monat    |
| Whisper STT        | <1 €/Monat      |
| TTS (optional)     | <1 €/Monat      |
| Telegram Bot       | kostenlos        |
| **Gesamt**         | **~7–11 €/Monat** |

---

## Setup-Schritte (Übersicht)

1. Hetzner Account erstellen → CX22 Server buchen (Ubuntu 24.04)
2. Telegram Bot via @BotFather erstellen → Bot Token speichern
3. Dieses Repo auf den Server clonen
4. `bot.py` schreiben (Telegram-Polling + Claude-Integration)
5. Secrets als Umgebungsvariablen setzen (`ANTHROPIC_API_KEY`, `BOT_TOKEN`)
6. Bot als systemd-Service einrichten (startet automatisch nach Reboot)

---

## Nächste Schritte

- [ ] Hetzner Server buchen
- [ ] Telegram Bot erstellen (@BotFather)
- [ ] `bot.py` implementieren
- [ ] Whisper STT integrieren
- [ ] Deployment auf Hetzner
- [ ] Optionales TTS für Sprachantworten
