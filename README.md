# Therapy Agent

KI-gestützter Therapeutensuche-Agent für München. Scrapt mehrere Plattformen, bewertet Praxen mit Claude gegen ein persönliches Profil und gibt die Ergebnisse sortiert nach Wartezeit aus.

## Voraussetzungen

```
pip install anthropic selenium
```

Chrome wird automatisch über Selenium Manager heruntergeladen.

```
setx ANTHROPIC_API_KEY dein-key   # dann Terminal neu starten
```

## Verwendung

```
py therapy_agent.py
```

## Konfiguration (`config.ini`)

### `[search]`
| Key | Beschreibung |
|---|---|
| `therapy_types` | Gewünschte Therapieverfahren (kommagetrennt) |
| `location` | Suchort (z.B. `München`) |
| `radius` | Suchradius in km |
| `min_score` | Mindestscore (1–10) für einen Treffer |
| `show_browser` | Browser sichtbar anzeigen (`true`/`false`) |

### `[payment]`
| Key | Beschreibung |
|---|---|
| `kassenpatienten` | GKV-Zulassung erforderlich |
| `privatpatient` | PKV akzeptiert |
| `selbstzahler` | Selbstzahler akzeptiert |

### `[preferences]`
| Key | Beschreibung |
|---|---|
| `therapist_gender` | `any`, `male`, `female` |
| `session_format` | `einzel`, `gruppe`, `online` (kommagetrennt) |
| `languages` | Therapiesprachen |
| `max_wait_weeks` | Maximale Wartezeit in Wochen (leer = egal) |
| `ignore_unknown_wait` | Praxen ohne Wartezeitangabe ausblenden (`true`/`false`) |

### `[platforms]`
| Platform | Beschreibung |
|---|---|
| `116117` | arztsuche.116117.de — offizielle GKV-Therapeutensuche |
| `therapie_de` | therapie.de — inkl. Wartezeiten auf Profilseiten |
| `jameda` | *(nicht implementiert)* |
| `therapeutenliste` | *(nicht implementiert)* |

### `[telegram]`
Optionaler Telegram-Bot für Benachrichtigungen. Gleicher Bot wie `job_search` verwendbar.

## Profil (`profile.txt`)

Freitext-Beschreibung der eigenen Situation, Wünsche und Prioritäten. Claude verwendet dieses Profil, um jede Praxis individuell zu bewerten.

## Datenpersistenz (`data/`)

| Datei | Inhalt |
|---|---|
| `seen_practices.json` | Alle bereits gesehenen Praxen mit Score, Pros/Cons |
| `sent_practices.json` | IDs der per Telegram gemeldeten Praxen |

Dateien löschen → beim nächsten Lauf werden alle Praxen neu bewertet.

## Projektstruktur

```
therapy_agent/
├── therapy_agent.py          # Einstiegspunkt
├── config.ini                # Konfiguration
├── profile.txt               # Persönliches Suchprofil
├── agent_prompt.txt          # Scoring-Anweisungen für Claude
├── scrapers/
│   ├── base.py               # Basis-Scraper-Klasse (Selenium)
│   ├── scraper_116117.py     # arztsuche.116117.de
│   └── scraper_therapie_de.py# therapie.de
├── skills/
│   ├── claude_scorer.py      # Batch-Scoring mit Claude Opus
│   ├── practice_store.py     # JSON-Persistenz (seen/sent)
│   └── telegram.py           # Telegram-Bot-Anbindung
└── data/                     # Automatisch erstellt
```
