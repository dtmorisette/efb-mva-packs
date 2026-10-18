"""Parse FAA MVA/MIA AIXM 5.1 XML into (mva_feet, rings) and footprints."""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET

GML = '{http://www.opengis.net/gml/3.2}'
AIXM = '{http://www.aixm.aero/schema/5.1}'


def parse_airspaces(path):
    """Yield-free list of (feet:int, rings:list[list[(lon,lat)]]).

    rings[0] is the exterior boundary; rings[1:] are holes. Coordinates are
    (lon, lat) in CRS84, as stored in the FAA posList (which is lon lat order).
    """
    tree = ET.parse(path)
    root = tree.getroot()
    out = []
    for asp in root.iter(AIXM + 'Airspace'):
        mva = None
        for ml in asp.iter(AIXM + 'minimumLimit'):
            if ml.text and ml.text.strip():
                mva = ml.text
                break
        if mva is None:
            continue
        digits = ''.join(c for c in mva if c.isdigit())
        if not digits:
            continue
        feet = int(digits)
        if feet == 0:
            continue
        for patch in asp.iter(GML + 'PolygonPatch'):
            rings = []
            ext = patch.find(GML + 'exterior')
            if ext is not None:
                for p in ext.iter(GML + 'posList'):
                    rings.append(_pairs(p.text))
            for interior in patch.findall(GML + 'interior'):
                for p in interior.iter(GML + 'posList'):
                    rings.append(_pairs(p.text))
            if rings and rings[0]:
                out.append((feet, rings))
    return out


def _pairs(text):
    nums = [float(v) for v in text.split()]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def vintage_tag(path):
    """Return the FAA data vintage from the top-level <description>, e.g.
    'GSO_MVA_FUS3_2024' or 'ROA_MVA_FUS3_2025_v1'. None if absent."""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        desc = root.find(GML + 'description')
        if desc is not None and desc.text:
            return desc.text.strip()
    except Exception:
        pass
    return None


def footprint(paths):
    """Union of all polygons across the given XML files as a shapely geometry.
    Returns None if nothing parses."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = []
    for path in paths:
        for _feet, rings in parse_airspaces(path):
            try:
                p = Polygon(rings[0], rings[1:]) if len(rings) > 1 else Polygon(rings[0])
                if not p.is_valid:
                    p = p.buffer(0)
                if p.area > 0:
                    polys.append(p)
            except Exception:
                continue
    return unary_union(polys) if polys else None
