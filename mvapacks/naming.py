"""Registry: ARTCC/facility config, name resolution, and file grouping."""
from __future__ import annotations
import glob
import os
import re
import yaml


class Registry:
    def __init__(self, cfg):
        self.artccs = cfg['artccs']            # code -> {name, facilities:[{code,name}]}
        # facility code -> (artcc_code, display_name)
        self._fac = {}
        self._layers = {}                      # facility code -> {chart key: layer code}
        for ac, blk in self.artccs.items():
            for f in blk.get('facilities', []):
                self._fac[f['code']] = (ac, f.get('name', f['code']))
                self._layers[f['code']] = f.get('layers') or {}

    @classmethod
    def load(cls, path):
        with open(path) as f:
            return cls(yaml.safe_load(f))

    def artcc_codes(self):
        return sorted(self.artccs)

    def facilities(self, artcc):
        return [f['code'] for f in self.artccs[artcc].get('facilities', [])]

    def artcc_label(self, artcc, style='combined'):
        name = self.artccs[artcc].get('name', artcc)
        if style == 'combined':
            return f'{name}-{artcc}' if name != artcc else artcc
        return artcc if style == 'code' else name

    def layer_override(self, facility, path):
        """Hand-set layer code for one chart file, from the facility's optional
        `layers:` map in artccs.yaml (keyed by chart_key), or None."""
        return self._layers.get(facility, {}).get(chart_key(path))

    def facility_label(self, code, style='combined'):
        # 'combined' only changes the center label; facility layers keep their codes
        if style in ('code', 'combined'):
            return code
        return self._fac.get(code, (None, code))[1]


# Tokens in an MVA file name that describe the chart rather than where it is.
_CHART_TYPE_TOKENS = {'VOR', 'MULTI'}


def _is_fus(token):
    return re.fullmatch(r'FUS\d', token, re.I) is not None


def chart_key(path):
    """File stem without the FUS3/FUS5 token, so one name covers both versions:
    D01_DEN_PUB_MVA_FUS3.xml -> 'D01_DEN_PUB_MVA'. Used as the artccs.yaml override key."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return '_'.join(t for t in stem.split('_') if not _is_fus(t))


def chart_layer_code(facility, path):
    """Layer code for one chart of a facility that publishes several. The first file-name
    token is the facility the FAA files the chart under; a location code after it names
    the chart (BOI_BZN_MVA_FUS3 -> 'BZN', D01_DEN_PUB_MVA_FUS3 -> 'DEN-PUB',
    TWF_BYI_VOR_MVA -> 'BYI'). With only a chart type left, keep facility + type
    (HLN_MVA_VOR -> 'HLN-VOR'); with nothing left it is the facility's main chart."""
    tokens = [t for t in os.path.splitext(os.path.basename(path))[0].split('_')[1:]
              if t.upper() != 'MVA' and not _is_fus(t)]
    places = [t for t in tokens if t.upper() not in _CHART_TYPE_TOKENS]
    if places:
        return '-'.join(places)
    return '-'.join([facility] + tokens)


def facility_files(data_dir, facility, kind='mva', fus=None):
    """Return the XML paths for a facility.

    kind='mva': match <FAC>_*.xml. If fus in (3,5), prefer files whose name
    contains FUS3/FUS5; if the facility has none of that type, fall back to all
    its files (e.g. MULTI/VOR-only facilities) so nothing is silently dropped.
    kind='mia': the facility code is the ARTCC; match <ARTCC>_TAV.xml.
    """
    if kind == 'mia':
        p = os.path.join(data_dir, f'{facility}_TAV.xml')
        return [p] if os.path.exists(p) else []
    allf = sorted(glob.glob(os.path.join(data_dir, f'{facility}_*.xml')))
    # keep only files whose first underscore-token is exactly this facility
    allf = [f for f in allf if os.path.basename(f).split('_')[0] == facility]
    # an ARTCC-level MVA facility (e.g. ZOA) shares a prefix with its MIA file
    allf = [f for f in allf if not os.path.basename(f).upper().endswith('_TAV.XML')]
    if fus in (3, 5):
        tag = f'FUS{fus}'
        sel = [f for f in allf if tag in os.path.basename(f).upper()]
        return sel if sel else allf
    return allf
