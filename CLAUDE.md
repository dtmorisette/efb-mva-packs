# CLAUDE.md — efb-mva-packs

Guidance for Claude Code working in this repo. Read this first.

## What this project is

A command-line tool that builds **FAA Minimum Vectoring Altitude (MVA)** and
**Minimum IFR Altitude (MIA)** chart overlays as **ForeFlight content packs**, for a
private pilot's EFB. The organizing unit is **one content pack per ARTCC**: each pack
contains every TRACON MVA chart in that center plus the overlying ARTCC MIA chart, as
separately toggleable layers.

This is a personal aviation side project (not navigation-certified — planning/situational
awareness only). The owner flies in the US; earlier work centered on ZDC (Washington
Center) facilities.

## Quickstart

```bash
pip install -r requirements.txt          # shapely, pillow, pyyaml  (conda/pip both fine)
python -m mvapacks.cli update             # pull FAA XML, hash, record vintage tags
python -m mvapacks.cli status --fus 3     # per-center: up-to-date / STALE / never built
python -m mvapacks.cli build --artcc ZDC  # build one; also --all, --stale, ZDC ZTL ...
```

Built packs → `dist/<PACK>.zip`. Import into ForeFlight by sharing the .zip into the app.

Entry point: `mvapacks/cli.py::main` (also exposed as the `mvapacks` console script via
`pyproject.toml`). There is no network access in some sandboxes; see Gotchas.

## Architecture (module map)

| File | Responsibility |
|------|----------------|
| `mvapacks/sources.py` | Scrape FAA index pages, download XML from `aeronav.faa.gov`, SHA-256 hashing, `sources.lock.json` read/write/diff. Also `ingest_local()` for offline snapshots. |
| `mvapacks/parse.py` | AIXM 5.1 → `(mva_feet, rings)`; `vintage_tag()`; `footprint()` (shapely union). |
| `mvapacks/labels.py` | `LabelRenderer` — bakes altitude labels as transparent PNGs in the locked style (per-glyph kerning). |
| `mvapacks/pack.py` | `build_layer_kmz()` (polygon boundaries + PNG label placemarks), `assemble_pack()` (manifest + provenance), `zip_pack()`. |
| `mvapacks/naming.py` | `Registry` (loads `config/artccs.yaml`, code↔full name resolution) and `facility_files()` (FUS selection + grouping). |
| `mvapacks/cli.py` | argparse subcommands: `update`, `status`, `build`, `list`. Owns `state/build_state.json`. |
| `config/artccs.yaml` | The facility registry: ARTCC→facilities, display names. **Editable by hand.** |
| `config/style.yaml` | Locked label/boundary house style (v1.7). |
| `assets/DejaVuSans.ttf` | Bundled font so rendering is identical across machines. |

Data/output dirs (gitignored): `data/` (FAA XML snapshot), `dist/` (built packs).
Tracked state: `state/sources.lock.json`, `state/build_state.json`.

## Key conventions — do not change without asking

- **Label/boundary style is LOCKED** in `config/style.yaml` (v1.7, user-approved after
  many iterations). Dark-purple labels `(80,35,150)`, pale lavender halo `(205,180,248,170)`
  radius 2, regular DejaVu Sans size 40 kern 3; purple polygon boundaries `ffff5a9a` width 3.
  Do not alter colors/font/halo without an explicit request.
- **Labels are baked PNG icons, not KML `LabelStyle`.** This is deliberate: ForeFlight
  renders a `LabelStyle` with a name "chip"; an icon-image PNG on a nameless placemark has
  no chrome. ForeFlight also does **not** support `Region`/`Lod` (no zoom-based hiding),
  `GroundOverlay`, or `StyleMap` normal+highlight — don't reach for those.
- **Defaults:** `--fus 3` (normal 3 nm buffer; FUS5 is degraded-mode 5 nm), `--names code`.
- **Boundaries are polygons** with `fill=0, outline=1`. ForeFlight adds its own faint light
  halo to polygon lines in both basemap modes — that's expected and looks good; don't try
  to defeat it.
- Pack naming: `<label> MVA-MIA` (e.g. `ZDC MVA-MIA`); layer names `<label> MVA` /
  `<ARTCC label> MIA`. `--names full` swaps codes for spelled-out names.

## Data sourcing (FAA-direct)

- Index pages: `faa.gov/air_traffic/flight_info/aeronav/digital_products/mva_mia/{mva,mia}`.
- Files: absolute links to `https://aeronav.faa.gov/MVA_Charts/aixm/<name>.xml`
  (MIA/TAV files live under the same `MVA_Charts` path despite the name).
- MVA: `<FAC>_MVA_FUS3.xml` / `_FUS5.xml`, plus variants (`MULTI`, `VOR`, multi-token like
  `BOI_BZN_MVA_FUS3.xml`, `D01_DEN_PUB_GJT_MVA_FUS5.xml`). MIA: `<ARTCC>_TAV.xml` (23).
- The FAA page has occasional row-label/file mismatches (a CLE row linking a CLT file,
  AVP rows linking AGS). The scraper trusts the **filename**, never the row text.
- **Change detection:** the in-file `validTime` is a useless placeholder (always 1980).
  Detection is by **SHA-256** of each source file (authoritative), with the FAA **vintage
  tag** from the XML `<description>` (e.g. `GSO_MVA_FUS3_2024`, `ROA_MVA_FUS3_2025_v1`) as a
  human-readable label surfaced in `status` and stamped into each pack's `provenance.json`.

## Facility → ARTCC assignment

Every MVA facility is assigned to the center whose **MIA (`<ARTCC>_TAV`) footprint it most
overlaps** (argmax of overlap fraction). Both datasets come from the same FAA feed, so the
mapping is self-consistent and reproducible. Result lives in `config/artccs.yaml`.

- The YAML is **the source of truth and is meant to be edited** — move a facility between
  centers, fix a name, adjust a boundary case. Regenerating it from scratch is a separate
  offline step (`python tools/gen_artccs.py`, needs `data/` populated), not part of the CLI.
- Boundary facilities (two centers split the footprint) and unverified names are annotated
  inline with `# boundary case` / `# VERIFY`.
- **Known decision pending:** PHL assigns to **ZNY** by footprint. The user's earlier
  hand-built ZDC pack included PHL in ZDC. If they want it in ZDC, move PHL's two lines
  from the ZNY block to the ZDC block in `artccs.yaml`. See `docs/DECISIONS.md`.

## Current state

- Style locked at **v1.7** (user-approved).
- Engine validated end-to-end against a local FAA snapshot: `update --from-local` →
  `status` → `build --artcc ZDC` reproduced the approved ZDC pack (correct layers, sector
  counts, and byte-identical label dimensions).
- **Not yet done:** building the other ARTCC packs for real against live FAA data; the
  optional weekly GitHub Action (deliberately deferred by the user); display-name cleanup.

## Gotchas

- Some execution sandboxes firewall `faa.gov`/`aeronav.faa.gov`. On the user's Mac the FAA
  is reachable and `update` (live download) works; in a restricted sandbox use
  `update --from-local <dir>` against an XML snapshot.
- `shapely` needs a working GEOS; `pip install shapely` normally bundles it. On a fresh env
  use `pip install -r requirements.txt` (add `--break-system-packages` only if pip refuses).
- The font is bundled; don't depend on a system DejaVu path.
- ForeFlight caching: deleting an imported pack can leave stale layers in the Maps list
  until the app is relaunched (believed a ForeFlight bug). `--bump-version` increments the
  manifest version so a re-import is recognized as newer.

## Testing

No formal test suite yet. The practical smoke test is the snapshot pipeline:
`python -m mvapacks.cli update --from-local <snapshot-dir> && python -m mvapacks.cli build --artcc ZDC`,
then inspect `dist/ZDC MVA-MIA.zip` (9 layers; GSO 10 / PCT 26 / ROA 27 / ZDC MIA 24 sectors
with the current data vintage).
