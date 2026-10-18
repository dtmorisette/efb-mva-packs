"""Build layer KMZs and assemble ForeFlight content packs."""
from __future__ import annotations
import json
import os
import zipfile

from .parse import parse_airspaces, vintage_tag
from .labels import LabelRenderer


def _rep_point(exterior):
    try:
        from shapely.geometry import Polygon
        return Polygon(exterior).representative_point().coords[0]
    except Exception:
        xs = [c[0] for c in exterior]
        ys = [c[1] for c in exterior]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


def _coords(ring):
    return " ".join(f"{lon},{lat}" for lon, lat in ring)


def build_layer_kmz(out_path, layer_name, xml_paths, renderer: LabelRenderer, style):
    """Render one toggleable layer (a facility's MVA sectors, or an ARTCC MIA)
    as a KMZ: purple polygon boundaries + baked PNG altitude labels."""
    edge_color = style['boundary']['color']
    edge_width = style['boundary']['width']
    icon_scale = style['label']['icon_scale']

    aspaces = []
    for p in xml_paths:
        aspaces.extend(parse_airspaces(p))
    feets = sorted({f for f, _ in aspaces})

    styles = [
        f'<Style id="edge"><LineStyle><color>{edge_color}</color>'
        f'<width>{edge_width}</width></LineStyle>'
        f'<PolyStyle><fill>0</fill><outline>1</outline></PolyStyle></Style>'
    ]
    icons = {}
    for f in feets:
        icons[f] = renderer.render(str(f))
        styles.append(
            f'<Style id="L{f}"><IconStyle><scale>{icon_scale}</scale>'
            f'<Icon><href>icons/{f}.png</href></Icon>'
            f'<hotSpot x="0.5" y="0.5" xunits="fraction" yunits="fraction"/>'
            f'</IconStyle></Style>'
        )

    placemarks = []
    for feet, rings in aspaces:
        ext = rings[0]
        poly = ('<Polygon><outerBoundaryIs><LinearRing><coordinates>'
                + _coords(ext) +
                '</coordinates></LinearRing></outerBoundaryIs>')
        for hole in rings[1:]:
            poly += ('<innerBoundaryIs><LinearRing><coordinates>'
                     + _coords(hole) +
                     '</coordinates></LinearRing></innerBoundaryIs>')
        poly += '</Polygon>'
        placemarks.append(f'<Placemark><styleUrl>#edge</styleUrl>{poly}</Placemark>')
        lon, lat = _rep_point(ext)
        placemarks.append(
            f'<Placemark><styleUrl>#L{feet}</styleUrl>'
            f'<Point><coordinates>{lon},{lat}</coordinates></Point></Placemark>'
        )

    doc = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>'
           + layer_name + '</name>\n'
           + ''.join(styles) + '\n' + ''.join(placemarks) + '\n</Document></kml>')

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('doc.kml', doc)
        for f, png in icons.items():
            z.writestr(f'icons/{f}.png', png)
    return len(feets)


def assemble_pack(pack_dir, pack_name, abbreviation, version, layers):
    """Write manifest.json + provenance.json. 'layers' is a list of
    {name, kmz_path, sources:[{file, vintage, sha256}]}. KMZs must already be
    written into pack_dir/layers/. Returns the pack directory path."""
    os.makedirs(os.path.join(pack_dir, 'layers'), exist_ok=True)
    manifest = {
        'name': pack_name,
        'abbreviation': abbreviation,
        'version': version,
        'organizationName': 'Custom',
    }
    with open(os.path.join(pack_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f)
    prov = {'pack': pack_name, 'version': version, 'layers': layers}
    with open(os.path.join(pack_dir, 'provenance.json'), 'w') as f:
        json.dump(prov, f, indent=2)
    return pack_dir


def zip_pack(pack_root, pack_name, out_zip):
    """Zip the pack_root/<pack_name> directory into out_zip."""
    base = os.path.join(pack_root, pack_name)
    os.makedirs(os.path.dirname(out_zip), exist_ok=True)
    if os.path.exists(out_zip):
        os.remove(out_zip)
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(base):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, pack_root)
                z.write(full, arc)
    return out_zip
