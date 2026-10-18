"""Registry: ARTCC/facility config, name resolution, and file grouping."""
from __future__ import annotations
import glob
import os
import yaml


class Registry:
    def __init__(self, cfg):
        self.artccs = cfg['artccs']            # code -> {name, facilities:[{code,name}]}
        # facility code -> (artcc_code, display_name)
        self._fac = {}
        for ac, blk in self.artccs.items():
            for f in blk.get('facilities', []):
                self._fac[f['code']] = (ac, f.get('name', f['code']))

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

    def facility_label(self, code, style='combined'):
        # 'combined' only changes the center label; facility layers keep their codes
        if style in ('code', 'combined'):
            return code
        return self._fac.get(code, (None, code))[1]


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
