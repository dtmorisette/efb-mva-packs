"""Fetch FAA MVA/MIA AIXM XML directly from aeronav.faa.gov and track changes.

The FAA publishes two index pages that link to the XML files:
  MVA: https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/mva_mia/mva
  MIA: https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/mva_mia/mia
Every download link is an absolute URL under https://aeronav.faa.gov/MVA_Charts/aixm/.
MVA files are <FAC>_MVA_*.xml; MIA files are <ARTCC>_TAV.xml.

Change detection is by SHA-256 of each source file, recorded in state/sources.lock.json.
The human-readable FAA vintage tag (from the XML <description>) is stored alongside.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
import urllib.request

INDEX = {
    'mva': 'https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/mva_mia/mva',
    'mia': 'https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/mva_mia/mia',
}
HREF_RE = re.compile(r'https://aeronav\.faa\.gov/[^\s"\'<>]+?\.xml', re.IGNORECASE)
UA = 'efb-mva-packs/1.0 (+https://github.com/)'


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def list_remote_xml():
    """Return {basename: url} for every XML linked on both index pages."""
    found = {}
    for kind, url in INDEX.items():
        html = _get(url).decode('utf-8', 'replace')
        for m in HREF_RE.findall(html):
            found[os.path.basename(m)] = m
    return found


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def download_all(dest_dir, delay=0.1, progress=None):
    """Download every remote XML into dest_dir. Returns {basename: sha256}."""
    os.makedirs(dest_dir, exist_ok=True)
    remote = list_remote_xml()
    hashes = {}
    for i, (name, url) in enumerate(sorted(remote.items())):
        data = _get(url)
        with open(os.path.join(dest_dir, name), 'wb') as f:
            f.write(data)
        hashes[name] = sha256_bytes(data)
        if progress:
            progress(i + 1, len(remote), name)
        time.sleep(delay)
    return hashes


def ingest_local(src_dir, dest_dir):
    """Copy an existing XML snapshot into dest_dir (offline / testing path).
    Returns {basename: sha256}."""
    import shutil
    os.makedirs(dest_dir, exist_ok=True)
    hashes = {}
    for name in sorted(os.listdir(src_dir)):
        if not name.lower().endswith('.xml'):
            continue
        sp = os.path.join(src_dir, name)
        shutil.copy2(sp, os.path.join(dest_dir, name))
        hashes[name] = sha256_file(sp)
    return hashes


# ---- lockfile ----

def load_lock(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'files': {}}


def save_lock(path, lock):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(lock, f, indent=2, sort_keys=True)


def diff_hashes(old_files, new_files):
    """Return (added, changed, removed) basename lists."""
    old = set(old_files)
    new = set(new_files)
    added = sorted(new - old)
    removed = sorted(old - new)
    changed = sorted(n for n in (new & old) if old_files[n].get('sha256') != new_files[n])
    return added, changed, removed
