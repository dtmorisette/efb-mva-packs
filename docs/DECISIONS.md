# Design decisions & history

Context for why the tool is shaped the way it is. Companion to `CLAUDE.md`.

## Origin

Started as hand-built KML/KMZ overlays for Garmin Pilot, then moved to ForeFlight after a
subscription. Many manual iterations on a single area (ZDC / Washington Center facilities)
established the look and the packaging model before this tool was written to generalize it.

## Why one pack per ARTCC

A ForeFlight content pack bundles many layers that toggle independently and re-import in
place (same pack name updates). Grouping by ARTCC gives a natural, manageable unit: all of a
center's TRACON MVA charts plus the overlying ARTCC MIA chart, each its own toggle. Merging
adjacent facilities into one file was tried and rejected (visual clutter, no independent
toggling) — hence one layer per facility.

## Label rendering as baked PNGs

ForeFlight renders KML `LabelStyle` text with a name "chip/pin." Baking each altitude into a
transparent PNG and placing it on a **nameless** placemark removes that chrome entirely.
Per-glyph drawing (not a single `draw.text`) gives control over kerning. The style
(dark-purple fill + restrained pale-lavender halo) was tuned to stay legible on **both**
ForeFlight light and dark basemaps. This went through ~a dozen rounds; v1.7 is the approved
result. Earlier rejected variants: black text/white halo (too heavy), desaturated-purple
halo too bright/bold, no-halo (too faint), ExtraLight font (too thin).

## ForeFlight capability limits (confirmed by testing)

- No `Region`/`Lod` → cannot hide layers above a zoom level (tested as a possible
  undocumented feature; labels stayed visible at all zooms). A feature request was drafted
  for the user to send to ForeFlight.
- No `GroundOverlay`, no `StyleMap` normal+highlight, no per-mode color schemes.
- ForeFlight adds its own faint light halo around polygon lines in both modes — pleasant,
  not controllable, left as-is.

## FAA as the data source (not a mirror)

Early work used the `dark/faa-mva-kml` GitHub mirror. The user explicitly wanted to source
from the FAA directly. The FAA publishes the same AIXM the mirror scraped; `sources.py` now
pulls it straight from `aeronav.faa.gov`. The mirror remains a useful reference/snapshot but
is not a dependency.

## Change detection

FAA MVA/MIA charts are amended per-facility on no fixed schedule (unlike the 56-day
instrument-procedure cycle). The in-file `validTime` is a placeholder (always 1980), so it
can't date anything. Two real signals are used: SHA-256 of each source file (authoritative
change trigger) and the `<description>` vintage tag (human-readable, e.g. `..._2025_v1`).
`status` and `build --stale` compare current data to what each pack was last built from.

## Facility → ARTCC assignment via MIA-TAV overlap

No authoritative public GIS layer cleanly maps TRACON facilities to centers, and TRACON
footprints straddle boundaries. The `@squawk/airspace-data` Class-A polygons were unlabeled.
The chosen method: each ARTCC's MIA (`_TAV`) chart tiles that center's whole footprint, so a
facility is assigned to the center its MVA footprint most overlaps (argmax overlap fraction).
Self-consistent (one FAA source) and reproducible. CLT correctly lands in ZTL, not ZDC.

### Boundary cases flagged for human review

Facilities where the top center wins by a thin margin (<55% or <15-pt lead) are annotated in
`config/artccs.yaml`. Notable:

- **ACY** — ZDC 50.7% vs ZNY 49.3% (near coin-flip)
- **GSO** — ZDC 51.7% vs ZTL 48.3%
- **PHL** — assigns to **ZNY** by footprint, but the user's earlier hand-built ZDC pack
  included it. Decision pending; override in the YAML if ZDC is preferred.
- Others: AZO, CKB, DSM, F11, MLU. `ZUA` (Guam) matches no CONUS center and is left
  unassigned.

## Naming

Default is **codes** (user's choice — many TRACON codes aren't tied to one airport, e.g.
PCT=Potomac, N90=New York). `--names full` uses spelled-out names from a table seeded from
OurAirports (airport-ident facilities) + a curated TRACON-name map. OurAirports is unreliable
for alphanumeric TRACON codes (A11/A80/C90… collide with unrelated heliports), so those come
from the curated map; a few names are marked `# VERIFY` for cleanup.

## Deferred / open

- Weekly GitHub Action to run `update` and flag staleness — intentionally deferred.
- Building all ARTCC packs against live FAA data.
- Display-name cleanup for `# VERIFY` entries.
- Resolve the PHL (and other boundary) assignments per the user's preference.
