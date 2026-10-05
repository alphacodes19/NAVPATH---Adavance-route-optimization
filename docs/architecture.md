# NAVPATH — Architecture

Originally built for Smart India Hackathon 2024 (see `docs/original_README.md`).
This doc exists because the person who built it didn't remember how it worked
five years later — so it's written for that reader.

## What it does

A pygame desktop app that plots a ship route across a grid of Indian coastal
waters. You pick a start and end point (click on the map, or type
lat/long), and it runs **A\* search** over the grid to find a route — but the
per-move cost isn't just distance. It factors in:

- **Wind direction** at that grid cell (`src/engine/wind_retriever.py`)
- **Ocean current direction** at that grid cell (`src/engine/current_retriever.py`)
- **Fuel efficiency** at that grid cell (`src/engine/fuel_retriever.py`)
- A **priority mode** you choose: cargo, passenger, or individually
  fuel / speed / comfort — each weights the above differently
  (`calculate_fscore()` in `src/app/main.py`)

Live weather (temperature, wind speed, description — shown as an overlay, not
used in pathfinding) comes from OpenWeatherMap via `src/app/weather_display.py`.

## Two layers

- **`src/engine/`** — pure data-lookup and math, no UI. This is the part
  worth keeping if this project is ever rebuilt as a web app: it doesn't care
  who's calling it.
- **`src/app/`** — the pygame UI that drives the engine.
- **`src/pipeline/`** — offline scripts that generate the `.pkl` files the
  engine reads, from raw weather/current/depth CSVs. Not needed to run the
  app, only to regenerate its data.

## Where the routing "intelligence" actually comes from

The `.pkl` files in `data/models/` aren't hand-written — most were trained.
`src/pipeline/data_training.py` (`WeatherHeuristicTrainer`) fits an XGBoost
model per day on weighted weather features (temperature, precipitation, wind)
to produce a "heuristic" value per grid cell, which `heuristics_generator.py`
then pickles into `heuristics_data.pkl`. That's what `h2_heuristic()` in
`main.py` reads. It's genuinely a reasonable thing to describe as "ML-assisted
routing" on a resume — this isn't just A* with a straight-line heuristic.

`Cargo.pkl` and `passenger.pkl` (used by `h3_heuristic()` / `h4_heuristic()`)
appear to be separately generated variants of the same idea, but nothing in
this codebase actually produces them — they were handed over already built.
If you want to regenerate them, you'd need to figure out what training run
produced them, or retrain equivalents yourself.

## Fixed since the initial restructure

- **Coordinate conversion tripling** — `grid_blocks_tool.py`'s local copy is
  gone; it now imports from `coord_convert.py` like `depth_cells.py` already
  did. One implementation left.
- **Dead fuel-scoring branch** — `f_score *= fuel_score` used to run before
  `f_score` had a value. Fixed so fuel efficiency actually discounts cost,
  the way wind/current alignment already did.
- **Individual mode with no sub-priority chosen scored everything as 0** —
  A* had nothing to distinguish neighbors by until Fuel/Speed/Comfort was
  picked. Now falls back to a sane default instead of a dead zero.
- **The L/B/H/Eff ship-dimension boxes were pure decoration** — now feed a
  size/efficiency multiplier into route cost (`get_ship_size_factor()` in
  `main.py`). Blank boxes behave exactly as before (neutral factor).
- **Land detection no longer depends on what's drawn on screen.** The
  original `is_black_pixel()` read live pixel colors back off the rendered
  display, which meant the ugly black land/sea overlay (`IndiaFore3.png`)
  had to actually be visible for pathfinding to work. `build_land_mask()`
  precomputes the same check once at startup off-screen — the overlay no
  longer needs to be drawn, so the visible map looks like the actual base
  map instead of a black silhouette.
- **Images were reloaded from disk on every frame** — `background()`
  (and the old `foreground()`) called `pygame.image.load()` every single
  frame. Now loaded once at startup.
- **The Manual/Automatic button label was backwards** — "Manual" was shown
  while the click-to-select-on-map mode was active, which is the opposite
  of what most people would expect "Manual" to mean. Relabeled to "Click on
  Map" / "Type Coordinates".
- **Invalid input only ever printed to the terminal** — added an on-screen
  status message (`set_status()` in `main.py`) so validation errors are
  visible during a demo, not just in a terminal nobody's watching.

## Known issues (still open)

1. **The data pipeline can't currently be re-run end to end.**
   `data_training.py` expects input files named `combined_<date>.csv`, but
   nothing in `data_preprocessing.py`'s output matches that name (it produces
   `data_<date>.csv` under `split_by_date/`). This doesn't block running the
   app — the pre-built `.pkl` files still work — but blocks retraining from
   scratch until this is reconciled.

2. **The depth-sensing feature is unwired.** `src/engine/depth_cells.py` and
   the GEBCO bathymetry data in `data/raw/` were built but never actually
   plugged into `calculate_fscore()` in `main.py`. Either finish wiring it in
   (adds real scope for a semester project) or remove it.

3. **`.env` had a live API key committed in plaintext**, including a second,
   unused key on its own line. Rotate the key before making this repo public.

4. **No automated tests.** `coord_convert`, the heuristic scorers, and A* on
   a small synthetic grid are all straightforward to unit test and would be
   a strong, cheap addition for a resume repo.

5. **No results summary or route export.** After a path is found, nothing
   is shown beyond the drawn line — no distance, estimated fuel burn, or way
   to export the route (CSV/GeoJSON) for use elsewhere.

## Data flow at a glance

```
data/raw/ (GEBCO .nc, source CSVs)
        │  src/pipeline/*_generator.py, cdf_converter.py, data_preprocessing.py
        ▼
data/processed/ (intermediate CSVs)
        │  src/pipeline/heuristics_generator.py (trains via data_training.py)
        ▼
data/models/*.pkl  ◄── this is what src/app/main.py actually reads at runtime
        │

        ▼
src/engine/*_retriever.py  ──►  src/app/main.py (A* + pygame UI)
```
