#!/usr/bin/env python3
"""Regenerate config/artccs.yaml from the FAA data in ./data.

Assignment rule: each MVA facility goes to the ARTCC whose MIA (<ARTCC>_TAV)
footprint it most overlaps (argmax overlap fraction). Requires that
`mvapacks update` (or `update --from-local`) has populated ./data first.

Usage:
    python tools/gen_artccs.py [--airports PATH_TO_ourairports_airports.csv]

Display names: ARTCC names + a curated TRACON-code map are built in. If an
OurAirports airports.csv is given, airport-ident facilities get real names;
everything else falls back to the code with a '# VERIFY' note. This file is a
STARTING POINT — config/artccs.yaml is meant to be hand-edited afterward, so
review boundary cases (annotated inline) before trusting the output.
"""
from __future__ import annotations
import argparse
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from mvapacks.parse import footprint  # noqa: E402

DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(ROOT, 'config', 'artccs.yaml')

ARTCC_NAMES = {
    'ZAB': 'Albuquerque', 'ZAN': 'Anchorage', 'ZAU': 'Chicago', 'ZBW': 'Boston',
    'ZDC': 'Washington', 'ZDV': 'Denver', 'ZFW': 'Fort Worth', 'ZHN': 'Honolulu',
    'ZHU': 'Houston', 'ZID': 'Indianapolis', 'ZJX': 'Jacksonville', 'ZKC': 'Kansas City',
    'ZLA': 'Los Angeles', 'ZLC': 'Salt Lake City', 'ZMA': 'Miami', 'ZME': 'Memphis',
    'ZMP': 'Minneapolis', 'ZNY': 'New York', 'ZOA': 'Oakland', 'ZOB': 'Cleveland',
    'ZSE': 'Seattle', 'ZSU': 'San Juan', 'ZTL': 'Atlanta', 'ZUA': 'Guam',
}
TRACON_NAMES = {
    'A11': 'Anchorage', 'A80': 'Atlanta', 'A90': 'Boston', 'C90': 'Chicago',
    'D01': 'Denver', 'D10': 'Dallas-Fort Worth', 'D21': 'Detroit', 'F11': 'Central Florida',
    'I90': 'Houston', 'L30': 'Las Vegas', 'M98': 'Minneapolis', 'N90': 'New York',
    'NCT': 'Northern California', 'P50': 'Phoenix', 'P80': 'Portland',
    'PCT': 'Potomac', 'R90': 'Omaha', 'S46': 'Seattle', 'S56': 'Salt Lake City',
    'SCT': 'Southern California', 'T75': 'St. Louis', 'U90': 'Tucson', 'Y90': 'Bradley',
    'ZHN': 'Honolulu', 'ZLC': 'Salt Lake City', 'ZOA': 'Oakland', 'ZSU': 'San Juan', 'ZUA': 'Guam',
}
TRACON_PAT = re.compile(r'^[A-Z]\d{2}$')
TRACON_3 = {'PCT', 'NCT', 'SCT'}


def load_airports(path):
    air = {}
    if not path:
        return air
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r['ident']:
                air[r['ident']] = r['name']
            if r.get('iata_code'):
                air.setdefault(r['iata_code'], r['name'])
    return air


def clean(name):
    for suf in [' International Airport', ' Regional Airport', ' Municipal Airport', ' Airport']:
        if name.endswith(suf):
            return name[:-len(suf)]
    return name


def display_name(code, air):
    if code in TRACON_NAMES:
        return TRACON_NAMES[code], True
    if TRACON_PAT.match(code) or code in TRACON_3:
        return code, False
    for k in (code, 'K' + code, 'P' + code):
        if k in air:
            return clean(air[k]), True
    return code, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--airports', help='OurAirports airports.csv for display names')
    args = ap.parse_args()
    air = load_airports(args.airports)

    # ARTCC footprints from MIA TAV
    artccs = {}
    for f in sorted(glob.glob(os.path.join(DATA, '*_TAV.xml'))):
        code = os.path.basename(f).split('_')[0]
        fp = footprint([f])
        if fp:
            artccs[code] = fp
    if not artccs:
        sys.exit(f'No *_TAV.xml in {DATA}. Run `mvapacks update` first.')

    # group MVA files by facility (first underscore token). Match the build path
    # in naming.py: every non-TAV xml, grouped by facility code. Filenames vary --
    # <FAC>_MVA_FUS3.xml, <FAC>_<apt>_MVA.xml, <FAC>_<apt>_VOR_MVA.xml, etc.
    fac_files = {}
    for f in glob.glob(os.path.join(DATA, '*.xml')):
        base = os.path.basename(f)
        if base.endswith('_TAV.xml'):
            continue
        code = base.split('_')[0]
        fac_files.setdefault(code, []).append(f)

    assign = {}
    for fac, flist in fac_files.items():
        fus3 = [x for x in flist if 'FUS3' in x.upper()]
        fp = footprint(fus3 if fus3 else flist)
        if fp is None or fp.area == 0:
            assign[fac] = (None, 0, 0)
            continue
        scores = sorted(((fp.intersection(a).area / fp.area, c) for c, a in artccs.items()),
                        reverse=True)
        top = scores[0]
        second = scores[1] if len(scores) > 1 else (0, None)
        assign[fac] = (top[1], round(top[0] * 100, 1), round(second[0] * 100, 1))

    by = {}
    for fac, (ac, p1, p2) in assign.items():
        if ac is None or p1 == 0:
            by.setdefault('_UNASSIGNED', []).append(fac)
        else:
            by.setdefault(ac, []).append(fac)

    lines = [
        '# efb-mva-packs facility registry',
        '# Auto-generated by tools/gen_artccs.py from FAA MIA (TAV) footprints (max-overlap).',
        '# Edit freely: move a facility between centers, fix a name, resolve a boundary case.',
        '',
        'artccs:',
    ]
    for ac in sorted(k for k in by if k != '_UNASSIGNED'):
        lines.append(f'  {ac}:')
        lines.append(f'    name: {ARTCC_NAMES.get(ac, ac)!r}')
        lines.append('    facilities:')
        for fac in sorted(by[ac]):
            _ac, p1, p2 = assign[fac]
            dn, ok = display_name(fac, air)
            amb = (p1 < 55 or (p1 - p2) < 15)
            note = ''
            if not ok and amb:
                note = f'   # VERIFY name; boundary: {p1}% {ac} vs {p2}%'
            elif not ok:
                note = '   # VERIFY name'
            elif amb:
                note = f'   # boundary case: {p1}% {ac} vs {p2}%'
            lines.append(f'      - code: {fac}')
            lines.append(f'        name: {dn!r}{note}')
    if '_UNASSIGNED' in by:
        lines.append('')
        lines.append(f"# Unassigned (no CONUS center overlap): {' '.join(sorted(by['_UNASSIGNED']))}")

    with open(OUT, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    n_fac = sum(len(v) for k, v in by.items() if k != '_UNASSIGNED')
    print(f'Wrote {OUT}: {len([k for k in by if k != "_UNASSIGNED"])} ARTCCs, {n_fac} facilities')
    if '_UNASSIGNED' in by:
        print('Unassigned:', ' '.join(sorted(by['_UNASSIGNED'])))


if __name__ == '__main__':
    main()
