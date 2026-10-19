"""Stage and publish a data release.

A release is:
  charts/<ARTCC>/<layer>.kmz   committed to the repo (individual charts, browsable on GitHub)
  dist/release/                attached to a GitHub release:
    <Pack_Name>.zip              one ForeFlight content pack per ARTCC
    MVA-MIA-All-Centers-<date>.zip  every pack in one download
    SHA256SUMS
  dist/release/RELEASE_NOTES.md  used as the release body (not attached)

stage() only writes files; publish() commits charts/ + state/, tags, pushes and
creates the GitHub release. KMZs are built deterministically (see pack.write_zip),
so unchanged charts are byte-identical and don't show up as git changes.
"""
from __future__ import annotations
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.parse

from .pack import write_zip
from .disclaimer import short_markdown

TAG_PREFIX = 'data-'


def _git(root, *args, check=True):
    r = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed: {r.stderr.strip()}')
    return r.stdout.strip()


def _asset_name(pack_name):
    # GitHub turns spaces in asset names into dots; use underscores instead
    return pack_name.replace(' ', '_') + '.zip'


def _link(path):
    return urllib.parse.quote(path)


def previous_tag(root):
    tags = _git(root, 'tag', '--list', f'{TAG_PREFIX}*', '--sort=-creatordate')
    return tags.splitlines()[0] if tags else None


def next_tag(root, today=None):
    base = TAG_PREFIX + (today or datetime.date.today()).isoformat()
    existing = set(_git(root, 'tag', '--list', f'{base}*').splitlines())
    if base not in existing:
        return base
    n = 2
    while f'{base}.{n}' in existing:
        n += 1
    return f'{base}.{n}'


def repo_slug(root):
    url = _git(root, 'remote', 'get-url', 'origin', check=False)
    m = re.search(r'github\.com[:/](.+?)(?:\.git)?$', url)
    return m.group(1) if m else None


def _sync_dir(src_files, dest_dir):
    """Make dest_dir's *.kmz exactly src_files ({name: path}). Returns (added, changed, removed)."""
    os.makedirs(dest_dir, exist_ok=True)
    added, changed, removed = [], [], []
    for name, src in sorted(src_files.items()):
        dst = os.path.join(dest_dir, name)
        with open(src, 'rb') as f:
            data = f.read()
        if os.path.exists(dst):
            with open(dst, 'rb') as f:
                if f.read() == data:
                    continue
            changed.append(name)
        else:
            added.append(name)
        with open(dst, 'wb') as f:
            f.write(data)
    for name in sorted(os.listdir(dest_dir)):
        if name.endswith('.kmz') and name not in src_files:
            os.remove(os.path.join(dest_dir, name))
            removed.append(name)
    return added, changed, removed


def _disclaimer(slug):
    return short_markdown(f'https://github.com/{slug}#disclaimer' if slug else '../README.md#disclaimer')


def _center_readme(ac, center, prov, releases_url, slug):
    lines = [f'# {center} ({ac}) MVA/MIA charts', '', _disclaimer(slug), '',
             'Each file is a standalone KMZ layer. The whole center is also available as one '
             f'ForeFlight content pack on the [Releases]({releases_url}) page.', '',
             '| Chart | Sectors | FAA vintage | Source file(s) |', '|---|---:|---|---|']
    for l in prov['layers']:
        vint = ', '.join(s.get('vintage') or '?' for s in l['sources'])
        files = ', '.join(f'`{s["file"]}`' for s in l['sources'])
        lines.append(f'| [{l["name"]}]({_link(l["name"] + ".kmz")}) | {l["sectors"]} | {vint} | {files} |')
    return '\n'.join(lines) + '\n'


def stage(root, reg, bstate, lock, pack_sources, hashes_for, fus=3, today=None):
    """Sync charts/ and build dist/release/. Raises RuntimeError if packs are stale."""
    dist = os.path.join(root, 'dist')
    charts = os.path.join(root, 'charts')
    out = os.path.join(dist, 'release')

    # every pack must be built from the current lockfile
    packs, problems = [], []
    for ac in reg.artcc_codes():
        srcs = pack_sources(reg, ac, fus)
        if not srcs:
            continue
        b = bstate.get(f'{ac}:FUS{fus}')
        if not b or b.get('source_hashes') != hashes_for(lock, srcs):
            problems.append(f'{ac} (stale or never built)')
            continue
        pack_dir = os.path.join(dist, '_packs', b['pack_name'])
        zip_path = os.path.join(dist, b['pack_name'] + '.zip')
        if not (os.path.isdir(pack_dir) and os.path.exists(zip_path)):
            problems.append(f'{ac} (built files missing from dist/)')
            continue
        with open(os.path.join(pack_dir, 'provenance.json')) as f:
            prov = json.load(f)
        packs.append({'artcc': ac, 'center': reg.artcc_label(ac, 'full'),
                      'pack_name': b['pack_name'], 'pack_dir': pack_dir,
                      'zip': zip_path, 'prov': prov})
    if problems:
        raise RuntimeError('Packs not ready: ' + ', '.join(problems)
                           + f". Run 'build --stale --fus {fus}' (or --all) first.")
    packs.sort(key=lambda p: p['center'])

    slug = repo_slug(root)
    releases_url = f'https://github.com/{slug}/releases/latest' if slug else '../../releases'

    # charts/
    summary = {'added': [], 'changed': [], 'removed': []}
    keep = set()
    for p in packs:
        ac = p['artcc']
        keep.add(ac)
        layer_dir = os.path.join(p['pack_dir'], 'layers')
        src = {fn: os.path.join(layer_dir, fn) for fn in os.listdir(layer_dir) if fn.endswith('.kmz')}
        a, c, r = _sync_dir(src, os.path.join(charts, ac))
        for k, names in zip(('added', 'changed', 'removed'), (a, c, r)):
            summary[k] += [f'{ac}/{n}' for n in names]
        with open(os.path.join(charts, ac, 'README.md'), 'w') as f:
            f.write(_center_readme(ac, p['center'], p['prov'], releases_url, slug))
    for d in sorted(os.listdir(charts)) if os.path.isdir(charts) else []:
        full = os.path.join(charts, d)
        if os.path.isdir(full) and d not in keep:
            summary['removed'] += [f'{d}/{n}' for n in os.listdir(full) if n.endswith('.kmz')]
            shutil.rmtree(full)
    index = ['# MVA/MIA charts by center', '', _disclaimer(slug), '',
             'Individual KMZ chart layers, one folder per ARTCC. Full ForeFlight content packs '
             f'are attached to each [release]({releases_url}).', '',
             '| Center | Charts |', '|---|---:|']
    for p in packs:
        index.append(f'| [{p["center"]} ({p["artcc"]})]({p["artcc"]}/) | {len(p["prov"]["layers"])} |')
    with open(os.path.join(charts, 'README.md'), 'w') as f:
        f.write('\n'.join(index) + '\n')

    # dist/release/
    tag = next_tag(root, today)
    date = tag[len(TAG_PREFIX):]
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    assets = []
    for p in packs:
        dst = os.path.join(out, _asset_name(p['pack_name']))
        shutil.copyfile(p['zip'], dst)
        assets.append(dst)
    full_name = f'MVA-MIA-All-Centers-{date}.zip'
    entries = {}
    for a in assets:
        with open(a, 'rb') as f:
            entries[os.path.basename(a)] = f.read()
    write_zip(os.path.join(out, full_name), entries)
    assets.insert(0, os.path.join(out, full_name))
    sums = []
    for a in assets:
        with open(a, 'rb') as f:
            sums.append(f'{hashlib.sha256(f.read()).hexdigest()}  {os.path.basename(a)}')
    with open(os.path.join(out, 'SHA256SUMS'), 'w') as f:
        f.write('\n'.join(sums) + '\n')
    assets.append(os.path.join(out, 'SHA256SUMS'))

    prev = previous_tag(root)
    notes = _release_notes(root, tag, prev, packs, full_name, fus)
    notes_path = os.path.join(out, 'RELEASE_NOTES.md')
    with open(notes_path, 'w') as f:
        f.write(notes)
    return {'tag': tag, 'prev': prev, 'assets': assets, 'notes': notes_path,
            'charts': summary, 'packs': packs}


def _chart_changes(root, prev):
    """Chart KMZs added/modified/deleted since prev tag (working tree vs tag)."""
    if not prev:
        return None
    out = _git(root, 'diff', '--name-status', prev, '--', 'charts/', check=False)
    untracked = _git(root, 'ls-files', '--others', '--exclude-standard', '--', 'charts/', check=False)
    rows = [l.split('\t', 1) for l in out.splitlines() if l.endswith('.kmz')]
    rows += [['A', l] for l in untracked.splitlines() if l.endswith('.kmz')]
    label = {'A': 'added', 'M': 'updated', 'D': 'removed'}
    return [(label.get(s[0], s), p[len('charts/'):-len('.kmz')]) for s, p in rows]


def _release_notes(root, tag, prev, packs, full_name, fus):
    slug = repo_slug(root)
    charts_url = f'https://github.com/{slug}/tree/{tag}/charts' if slug else 'charts/'
    nlayers = sum(len(p['prov']['layers']) for p in packs)
    lines = [f'FAA Minimum Vectoring Altitude (MVA) and Minimum IFR Altitude (MIA) chart overlays '
             f'for ForeFlight, one content pack per ARTCC: {len(packs)} centers, {nlayers} charts '
             f'(FUS{fus}).', '', _disclaimer(slug), '',
             '## Downloads', '',
             f'- **All centers:** `{full_name}` contains every pack below. Unzip it, then import '
             'the packs you want.',
             '- **One center:** download its pack zip below and share it to ForeFlight.',
             f'- **Single charts:** individual KMZ layers are in [`charts/`]({charts_url}).', '',
             '| Center | Pack | Charts |', '|---|---|---:|']
    for p in packs:
        lines.append(f'| {p["center"]} ({p["artcc"]}) | `{_asset_name(p["pack_name"])}` '
                     f'| {len(p["prov"]["layers"])} |')
    lines += ['', '## Changes', '']
    changes = _chart_changes(root, prev)
    if changes is None:
        lines.append('Initial release.')
    elif not changes:
        lines.append(f'No chart changes since {prev}.')
    else:
        lines.append(f'Since {prev}:')
        lines += [f'- {name}: {what}' for what, name in sorted(changes, key=lambda x: x[1])]
    return '\n'.join(lines) + '\n'


def dirty_paths(root):
    """Uncommitted changes outside charts/ and state/ (a release must not depend on them)."""
    out = _git(root, 'status', '--porcelain', check=False)
    paths = [l[3:] for l in out.splitlines()]
    return [p for p in paths if not (p.startswith('charts/') or p.startswith('state/'))]


def publish(root, staged):
    """Commit charts/ + state/, tag, push, and create the GitHub release."""
    tag = staged['tag']
    _git(root, 'add', '--', 'charts', 'state')
    if _git(root, 'diff', '--cached', '--name-only', '--', 'charts', 'state'):
        _git(root, 'commit', '-m', f'Data release {tag}', '--', 'charts', 'state')
    _git(root, 'tag', '-a', tag, '-m', f'Data release {tag}')
    branch = _git(root, 'rev-parse', '--abbrev-ref', 'HEAD')
    _git(root, 'push', 'origin', branch, tag)
    r = subprocess.run(['gh', 'release', 'create', tag, *staged['assets'],
                        '--title', f'MVA/MIA charts {tag[len(TAG_PREFIX):]}',
                        '--notes-file', staged['notes']],
                       cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'gh release create failed (tag {tag} is pushed): {r.stderr.strip()}')
    return r.stdout.strip()
