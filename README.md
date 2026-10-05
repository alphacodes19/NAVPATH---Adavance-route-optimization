# NAVPATH — Ship Route Navigation

A pygame app that plots optimized ship routes across Indian coastal waters
using A* search, weighted by live wind, ocean current, and fuel-efficiency
data — with different routing priorities for cargo, passenger, fuel, speed,
or comfort.

Originally built for Smart India Hackathon 2024. See
[`docs/architecture.md`](docs/architecture.md) for how it actually works and
a list of known issues — read that first if you're picking this project back
up after a while.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your own OpenWeatherMap API key
(`api_key=...`). **Do not reuse the key that was previously in this repo's
`.env` — rotate it**, it was committed in plaintext.

## Run

```bash
python -m src.app.main
```

Runs fullscreen. Click a start point and an end point on the map (or type
lat/long into the input boxes), pick a routing priority, and hit Start.

## Project layout

```
src/
  app/       pygame UI — the thing you actually run
  engine/    pathfinding + data lookups (wind, current, fuel, heuristics) — no UI dependency
  pipeline/  offline scripts that regenerate the .pkl files in data/models/
  tools/     grid_blocks_tool.py — used to hand-mark obstacle cells on the map
  config.py  every file path used by the project, in one place
data/
  models/      .pkl files the running app reads
  raw/         source datasets (GEBCO bathymetry)
  processed/   intermediate CSVs from the pipeline
  snapshots/   archived historical run outputs, not read by the app
assets/        map images, intro video
docs/          architecture notes + the original README
archive/unused/  files that were unclear, unused, or duplicated — kept, not deleted
```

## Regenerating data (optional)

Only needed if you want to retrain the routing heuristics rather than use the
ones already in `data/models/`. See `docs/architecture.md` — the pipeline
currently has a gap that stops it running end-to-end from scratch.
