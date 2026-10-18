"""Command-line interface for efb-mva-packs.

Subcommands:
  update   Download FAA XML (or ingest a local snapshot), hash, update lockfile.
  status   Show, per ARTCC, whether a rebuild is needed (stale vs built).
  build    Build content pack(s): --all | --stale | --artcc ZDC [ZTL ...]
  list     List known ARTCCs and their facilities.
  release  Sync charts/ and stage dist/release/; --publish commits, tags and creates the GitHub release.

Global data lives under the repo:
  data/            cloned FAA XML (gitignored)
  state/           sources.lock.json, build_state.json
  dist/            built <PACK>.zip (gitignored)
  charts/          released per-chart KMZs, one folder per ARTCC (committed)
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import yaml

from . import sources, pack as packmod, release as releasemod
from .naming import Registry, facility_files
from .labels import LabelRenderer
from .parse import vintage_tag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
STATE = os.path.join(ROOT, 'state')
DIST = os.path.join(ROOT, 'dist')
LOCK = os.path.join(STATE, 'sources.lock.json')
BUILD_STATE = os.path.join(STATE, 'build_state.json')
CFG_ARTCCS = os.path.join(ROOT, 'config', 'artccs.yaml')
CFG_STYLE = os.path.join(ROOT, 'config', 'style.yaml')


def _load_style():
    with open(CFG_STYLE) as f:
        return yaml.safe_load(f)


def _load_build_state():
    if os.path.exists(BUILD_STATE):
        with open(BUILD_STATE) as f:
            return json.load(f)
    return {}


def _save_build_state(st):
    os.makedirs(STATE, exist_ok=True)
    with open(BUILD_STATE, 'w') as f:
        json.dump(st, f, indent=2, sort_keys=True)


# ---- relevant source files for an ARTCC pack ----

def _pack_sources(reg: Registry, artcc: str, fus: int):
    """Return {basename: path} of every XML a pack depends on (facility MVA
    files of the chosen FUS + the ARTCC MIA TAV)."""
    files = {}
    for fac in reg.facilities(artcc):
        for p in facility_files(DATA, fac, 'mva', fus):
            files[os.path.basename(p)] = p
    for p in facility_files(DATA, artcc, 'mia'):
        files[os.path.basename(p)] = p
    return files


def _hashes_for(lock, basenames):
    return {b: lock['files'].get(b, {}).get('sha256') for b in basenames}


# ---- commands ----

def cmd_update(args):
    prev = sources.load_lock(LOCK)
    failed = {}
    if args.from_local:
        print(f'Ingesting local snapshot: {args.from_local}')
        new_hashes = sources.ingest_local(args.from_local, DATA)
    else:
        print('Downloading FAA XML from aeronav.faa.gov ...')

        def prog(i, n, name):
            sys.stdout.write(f'\r  {i}/{n}  {name:<32}')
            sys.stdout.flush()
        new_hashes, failed = sources.download_all(DATA, progress=prog)
        print()

    # build new lock with vintage tags
    new_files = {}
    for name, sha in new_hashes.items():
        vt = vintage_tag(os.path.join(DATA, name))
        new_files[name] = {'sha256': sha, 'vintage': vt}
    # a failed download keeps its previous lock entry so it isn't reported as removed
    for name in failed:
        if name in prev['files']:
            new_files[name] = prev['files'][name]
            new_hashes[name] = prev['files'][name]['sha256']
    added, changed, removed = sources.diff_hashes(prev['files'], new_hashes)
    sources.save_lock(LOCK, {'files': new_files})
    print(f'Lockfile updated: {len(new_files)} files '
          f'(+{len(added)} new, ~{len(changed)} changed, -{len(removed)} removed)')
    for n in changed:
        old_v = prev['files'].get(n, {}).get('vintage')
        print(f'  changed: {n}  {old_v} -> {new_files[n]["vintage"]}')
    if added:
        print('  new: ' + ' '.join(added[:20]) + (' ...' if len(added) > 20 else ''))
    if failed:
        print(f'WARNING: {len(failed)} file(s) failed to download (re-run update to retry):')
        for n, err in sorted(failed.items()):
            print(f'  {n}: {err}')
        return 1


def cmd_status(args):
    reg = Registry.load(CFG_ARTCCS)
    lock = sources.load_lock(LOCK)
    if not lock['files']:
        print("No data yet. Run 'mvapacks update' first.")
        return
    bstate = _load_build_state()
    fus = args.fus
    rows = []
    for ac in reg.artcc_codes():
        srcs = _pack_sources(reg, ac, fus)
        if not srcs:
            continue
        cur = _hashes_for(lock, srcs)
        key = f'{ac}:FUS{fus}'
        built = bstate.get(key)
        if not built:
            state = 'never built'
        elif built.get('source_hashes') != cur:
            state = 'STALE'
        else:
            state = 'up-to-date'
        ver = built.get('version') if built else '-'
        rows.append((ac, reg.artcc_label(ac, 'full'), len(srcs), state, ver))
    print(f'{"ARTCC":6} {"Center":16} {"srcs":>4}  {"state":12} version')
    for ac, name, n, state, ver in rows:
        print(f'{ac:6} {name:16.16} {n:>4}  {state:12} {ver}')


def _build_one(reg, style, renderer, ac, fus, names, bump, bstate, lock):
    label = reg.artcc_label(ac, names)
    pack_name = f'{label} MVA-MIA'
    abbrev = f'{ac}-MVA-MIA'
    pack_root = os.path.join(DIST, '_packs')
    pack_dir = os.path.join(pack_root, pack_name)
    layers_dir = os.path.join(pack_dir, 'layers')
    # clean any previous build dir for this pack
    import shutil
    if os.path.exists(pack_dir):
        shutil.rmtree(pack_dir)
    os.makedirs(layers_dir, exist_ok=True)

    layer_meta = []
    # facility MVA layers
    for fac in reg.facilities(ac):
        xmls = facility_files(DATA, fac, 'mva', fus)
        if not xmls:
            continue
        flabel = reg.facility_label(fac, names)
        lname = f'{flabel} MVA'
        kmz = os.path.join(layers_dir, f'{lname}.kmz')
        n = packmod.build_layer_kmz(kmz, lname, xmls, renderer, style)
        layer_meta.append({'name': lname, 'sectors': n,
                           'sources': [{'file': os.path.basename(x),
                                        'vintage': lock['files'].get(os.path.basename(x), {}).get('vintage'),
                                        'sha256': lock['files'].get(os.path.basename(x), {}).get('sha256')}
                                       for x in xmls]})
    # ARTCC MIA layer
    mia = facility_files(DATA, ac, 'mia')
    if mia:
        # 'combined' names the pack only; the MIA layer keeps the bare center code
        lname = f'{reg.artcc_label(ac, "full" if names == "full" else "code")} MIA'
        kmz = os.path.join(layers_dir, f'{lname}.kmz')
        n = packmod.build_layer_kmz(kmz, lname, mia, renderer, style)
        layer_meta.append({'name': lname, 'sectors': n,
                           'sources': [{'file': os.path.basename(mia[0]),
                                        'vintage': lock['files'].get(os.path.basename(mia[0]), {}).get('vintage'),
                                        'sha256': lock['files'].get(os.path.basename(mia[0]), {}).get('sha256')}]})

    # version
    key = f'{ac}:FUS{fus}'
    prev_ver = bstate.get(key, {}).get('version', 0)
    if isinstance(prev_ver, str):
        try: prev_ver = float(prev_ver)
        except ValueError: prev_ver = 0
    version = round(prev_ver + 0.1, 1) if (bump and prev_ver) else (prev_ver or 1.0)

    packmod.assemble_pack(pack_dir, pack_name, abbrev, version, layer_meta)
    out_zip = os.path.join(DIST, f'{pack_name}.zip')
    packmod.zip_pack(pack_root, pack_name, out_zip)

    # record build state
    srcs = _pack_sources(reg, ac, fus)
    bstate[key] = {'version': version,
                   'pack_name': pack_name,
                   'source_hashes': _hashes_for(lock, srcs)}
    return out_zip, len(layer_meta), version


def cmd_build(args):
    reg = Registry.load(CFG_ARTCCS)
    style = _load_style()
    renderer = LabelRenderer(style, ROOT)
    lock = sources.load_lock(LOCK)
    if not lock['files']:
        print("No data yet. Run 'mvapacks update' first.")
        return
    bstate = _load_build_state()
    fus = args.fus

    # pick targets
    if args.artcc:
        targets = [a.upper() for a in args.artcc]
    elif args.all:
        targets = reg.artcc_codes()
    elif args.stale:
        targets = []
        for ac in reg.artcc_codes():
            srcs = _pack_sources(reg, ac, fus)
            if not srcs:
                continue
            key = f'{ac}:FUS{fus}'
            built = bstate.get(key)
            if not built or built.get('source_hashes') != _hashes_for(lock, srcs):
                targets.append(ac)
    else:
        print('Nothing to do: pass --all, --stale, or --artcc CODE')
        return

    if not targets:
        print('All selected packs are up-to-date.')
        return
    os.makedirs(DIST, exist_ok=True)
    for ac in targets:
        if ac not in reg.artccs:
            print(f'  ! unknown ARTCC {ac}, skipping')
            continue
        out_zip, nlayers, ver = _build_one(reg, style, renderer, ac, fus,
                                            args.names, args.bump_version, bstate, lock)
        print(f'  built {os.path.basename(out_zip)}  ({nlayers} layers, FUS{fus}, v{ver})')
    _save_build_state(bstate)


def cmd_list(args):
    reg = Registry.load(CFG_ARTCCS)
    for ac in reg.artcc_codes():
        facs = reg.facilities(ac)
        print(f'{ac} ({reg.artcc_label(ac, "full")}): {len(facs)}  ' + ' '.join(facs))


def cmd_release(args):
    reg = Registry.load(CFG_ARTCCS)
    lock = sources.load_lock(LOCK)
    if args.publish:
        dirty = releasemod.dirty_paths(ROOT)
        if dirty:
            print('Commit or stash these changes first (a release is tagged from HEAD):')
            for p in dirty:
                print(f'  {p}')
            return 1
    try:
        st = releasemod.stage(ROOT, reg, _load_build_state(), lock,
                              _pack_sources, _hashes_for, fus=args.fus)
    except RuntimeError as e:
        print(e)
        return 1
    c = st['charts']
    print(f"Release {st['tag']}  (previous: {st['prev'] or 'none'})")
    print(f"  charts/: {len(c['added'])} added, {len(c['changed'])} changed, {len(c['removed'])} removed")
    for k in ('added', 'changed', 'removed'):
        for n in c[k][:10]:
            print(f'    {k}: {n}')
        if len(c[k]) > 10:
            print(f'    ... {len(c[k]) - 10} more {k}')
    total = 0
    print('  release assets:')
    for a in st['assets']:
        size = os.path.getsize(a)
        total += size
        print(f'    {os.path.basename(a):<44} {size / 1e6:6.2f} MB')
    print(f'    {"total":<44} {total / 1e6:6.2f} MB')
    print(f"  notes: {os.path.relpath(st['notes'], ROOT)}")

    changes = releasemod._chart_changes(ROOT, st['prev'])
    if not args.publish:
        print('Dry run: nothing committed or published. Re-run with --publish to release.')
        return
    if changes == [] and not args.force:
        print(f"No chart changes since {st['prev']}; not publishing (use --force to override).")
        return 1
    url = releasemod.publish(ROOT, st)
    print(f'Published {url}')


def main(argv=None):
    p = argparse.ArgumentParser(prog='mvapacks', description='Build FAA MVA/MIA ForeFlight content packs.')
    sub = p.add_subparsers(dest='cmd', required=True)

    pu = sub.add_parser('update', help='Download FAA XML and update the lockfile')
    pu.add_argument('--from-local', metavar='DIR', help='Ingest an existing XML snapshot instead of downloading')
    pu.set_defaults(func=cmd_update)

    ps = sub.add_parser('status', help='Show which ARTCC packs are stale')
    ps.add_argument('--fus', type=int, choices=(3, 5), default=3)
    ps.set_defaults(func=cmd_status)

    pb = sub.add_parser('build', help='Build content pack(s)')
    g = pb.add_mutually_exclusive_group()
    g.add_argument('--all', action='store_true', help='Build every ARTCC pack')
    g.add_argument('--stale', action='store_true', help='Build only packs whose source data changed')
    g.add_argument('--artcc', nargs='+', metavar='CODE', help='Build specific ARTCC(s), e.g. ZDC ZTL')
    pb.add_argument('--fus', type=int, choices=(3, 5), default=3, help='MVA chart version (3=normal, 5=degraded)')
    pb.add_argument('--names', choices=('combined', 'code', 'full'), default='combined',
                    help="Label style: combined -> 'Washington-ZDC MVA-MIA' (default), code -> 'ZDC MVA-MIA', full -> 'Washington MVA-MIA'")
    pb.add_argument('--bump-version', action='store_true', help='Increment manifest version (forces FF re-import refresh)')
    pb.set_defaults(func=cmd_build)

    pl = sub.add_parser('list', help='List ARTCCs and facilities')
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser('release', help='Stage (and optionally publish) a GitHub data release')
    pr.add_argument('--fus', type=int, choices=(3, 5), default=3)
    pr.add_argument('--publish', action='store_true',
                    help='Commit charts/ + state/, tag data-YYYY-MM-DD, push, and create the GitHub release')
    pr.add_argument('--force', action='store_true', help='Publish even if no chart changed since the last release')
    pr.set_defaults(func=cmd_release)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
