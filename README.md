# efb-mva-packs

Build FAA **Minimum Vectoring Altitude (MVA)** and **Minimum IFR Altitude (MIA)**
chart overlays as ForeFlight **content packs** — one pack per ARTCC, each containing
every TRACON MVA chart in that center plus the overlying ARTCC MIA chart, as
separately toggleable layers.

Data is sourced **directly from the FAA** (`aeronav.faa.gov`), not a third-party mirror.

## Install

```bash
pip install -r requirements.txt     # shapely, pillow, pyyaml
# or: pip install -e .   (then use the `mvapacks` command)
```

## Usage

```bash
# 1. Pull the latest FAA XML and record hashes + vintage tags
python -m mvapacks.cli update

# 2. See which centers have changed data since you last built
python -m mvapacks.cli status --fus 3

# 3. Build packs
python -m mvapacks.cli build --artcc ZDC              # one center
python -m mvapacks.cli build --artcc ZDC ZTL ZNY      # several
python -m mvapacks.cli build --all                    # every center
python -m mvapacks.cli build --stale                  # only centers whose data changed
```

Built packs land in `dist/<PACK>.zip`, ready to import into ForeFlight
(Settings → import, or share the .zip into the app).

### Options

| Flag | Meaning |
|------|---------|
| `--fus {3,5}` | Which MVA chart to use. **FUS3** = normal (3 nm terrain/obstacle buffer). **FUS5** = degraded-mode (5 nm, larger coverage). Default 3. |
| `--names {combined,code,full}` | Layer/pack naming. `combined` → pack `Washington-ZDC MVA-MIA`; layers keep codes (`GSO MVA`, `ZDC MIA`). `code` → `ZDC MVA-MIA`. `full` → `Washington MVA-MIA`, `Piedmont Triad MVA`. Default `combined`. |
| `--bump-version` | Increment the pack's `manifest.json` version. ForeFlight uses this field to recognise a re-imported pack as newer, so bump when the data changed. |

## How update detection works

FAA MVA/MIA charts are **not** on a fixed cycle like instrument procedures — each
facility is amended irregularly. The in-file `validTime` is a useless placeholder
(always 1980), so this tool detects change two ways:

- **SHA-256** of each source XML → the authoritative "did it change" trigger, stored
  in `state/sources.lock.json`.
- The FAA **vintage tag** from the XML `<description>` (e.g. `GSO_MVA_FUS3_2024`,
  `ROA_MVA_FUS3_2025_v1`) → a human-readable label shown in `status` and stamped into
  each pack's `provenance.json`.

`update` re-downloads from the FAA, re-hashes, and reports what changed. `status` and
`build --stale` compare the current data against what each pack was last built from
(recorded in `state/build_state.json`).

## Facility → ARTCC assignment

Every MVA facility is assigned to the center whose MIA (`<ARTCC>_TAV`) footprint it
most overlaps — both datasets come from the same FAA source, so the mapping is
self-consistent and reproducible. The result lives in `config/artccs.yaml`, which is
**editable**: move a facility between centers, fix a display name, or adjust a
boundary case. Boundary facilities (where two centers split the footprint) and
unverified names are annotated inline with `# boundary case` / `# VERIFY`.

## Style

The label/boundary house style is locked in `config/style.yaml` (dark-purple labels,
restrained lavender halo, purple polygon boundaries) and renders identically on light
and dark ForeFlight basemaps. The DejaVu Sans font is bundled in `assets/` so output
is reproducible across machines.

## Layout

```
mvapacks/        engine: sources, parse, labels, pack, naming, cli
config/          artccs.yaml (registry), style.yaml (locked style)
assets/          bundled font
state/           sources.lock.json, build_state.json  (tracked)
data/            FAA XML snapshot                      (gitignored)
dist/            built packs                           (gitignored)
```

## Data source & attribution

Chart data © FAA, public domain, from
<https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/mva_mia/>.
For planning/EFB visualisation only — not for navigation.
