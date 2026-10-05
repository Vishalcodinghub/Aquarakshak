# AquaGuard - Smart Water Quality & Purification Dashboard (Python)

## Run (no installation, no pip)
- **Windows:** double-click `run.bat`   (or:  `python run.py`)
- **macOS / Linux:** `./run.sh`          (or:  `python3 run.py`)

The dashboard opens automatically in your browser at http://localhost:8000/
(if port 8000 is busy, the next free port is used - see the console).
Stop with Ctrl+C. Options: `--port 9000`, `--no-browser`, `--host 0.0.0.0` (share on your network).

## What's inside
| Path | Purpose |
|---|---|
| `run.py` | Launcher (starts server + opens browser) |
| `aquaguard/engine.py` | Python simulation: sensors, scenarios, quality score, alerts, purification pipeline, tanks, history |
| `aquaguard/server.py` | Built-in web server + JSON API |
| `static/index.html`, `css/`, `js/` | The dashboard UI (Chart.js bundled - works offline) |
| `data/store.json` | Auto-created; saves history, alerts and settings between runs |

## API (mock IoT gateway)
`GET /api/health` `GET /api/state` `GET /api/snapshot` `GET /api/history?hours=24` `GET /api/export.csv`
`POST /api/simulate {"scenario":"safe|polluted|mining"}` `POST /api/purification {"cmd":"start|stop|reset|emergency|mode"}`
`POST /api/monitoring` `POST /api/alerts` `POST /api/settings` `POST /api/reset` `POST /api/seed` `POST /api/wipe`

## Troubleshooting
- "python not found": install Python 3.8+ from python.org (tick *Add to PATH*).
- Blank page / old data: delete `data/store.json` and restart.
- All readings are simulated - not real water-safety measurements.
