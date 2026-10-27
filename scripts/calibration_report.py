"""Fit residuals of the three oriented Chelyabinsk cameras, as the solution uses them -> events/chelyabinsk-2013/calibration.json,
and each camera's offset from CBET 3423's plane -> validation/chelyabinsk-2013/calibration-vs-cbet.json.

The plan's acceptance gate (0.3 deg, and 0.5 deg leaving one landmark out) was written for cameras fitted to a few
landmarks. These cameras are fitted mostly to annotated lines (verticals, and street edges whose bearing comes from
OSM), so the record is each evidence group's RMS residual, plus how far a refit from the same evidence lands from the
camera stored in picks.json (zero means picks.json holds exactly this fit).
Small fit residuals only say the evidence agrees with itself. The external check, 'vs_cbet_plane_deg', is the angle
between each fireball ray and the plane through the camera and CBET 3423's published path: it uses the published
answer, so it is written to validation/, which the agent never reads.
Usage: .venv/bin/python scripts/calibration_report.py
"""
import json
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import EVENT, PICKS, ROOT, TRUTH, kamensk_camera_v2, korkino_camera, rows, tyumen_camera  # noqa: E402
from testigos.geo import enu_basis, to_ecef  # noqa: E402

BUILDERS = {'2': lambda: kamensk_camera_v2(with_report=True), '10': lambda: korkino_camera(79.5, with_report=True),
            '48': lambda: tyumen_camera(with_report=True)}


def vs_cbet_plane(cam, pos, key):
    path = json.loads(TRUTH.read_text())['trajectory']
    a, b = (to_ecef(p['lat'], p['lon'], p['h_km'] * 1000) for p in (path[0], path[-1]))
    o = to_ecef(*pos)
    n = np.cross(a - o, b - o)
    n /= np.linalg.norm(n)
    rays = np.array([cam.unproject(r['centroid']) for r in rows(key)]) @ enu_basis(pos[0], pos[1])
    ang = np.degrees(np.arcsin(np.clip(rays @ n, -1, 1)))
    p10, p50, p90 = np.percentile(ang, [10, 50, 90])
    return {'rays': len(ang), 'median_deg': round(float(p50), 2), 'p10_deg': round(float(p10), 2), 'p90_deg': round(float(p90), 2)}


def main():
    out, vs_cbet = {}, {}
    for no, build in BUILDERS.items():
        cam, pos, report = build()
        groups = {k: g for k, g in report.items() if g['n']}
        n = sum(g['n'] for g in groups.values())
        rms_px = math.sqrt(sum(g['n'] * g['rms_px'] ** 2 for g in groups.values()) / n)
        used = PICKS[f'chelyabinsk-2013-{no}']['camera']
        out[no] = {'evidence': {k: {'residuals': g['n'], 'rms_px': round(g['rms_px'], 2), 'rms_deg': round(g['rms_deg'], 3)}
                                for k, g in groups.items()},
                   'rms_px': round(rms_px, 2), 'rms_deg': round(math.degrees(rms_px / cam.focal), 3),
                   'refit_minus_picks': {k: float(round(getattr(cam, k) - used.get(k, 0.0), 3)) + 0.0 for k in ('yaw', 'pitch', 'roll', 'hfov', 'k1')}}
        vs_cbet[no] = {'vs_cbet_plane_deg': vs_cbet_plane(cam, pos, f'chelyabinsk-2013-{no}')}
        print(f"{no}: {out[no]['rms_deg']} deg RMS over {n} residuals; refit minus picks.json {out[no]['refit_minus_picks']}; "
              f"off CBET's plane {vs_cbet[no]['vs_cbet_plane_deg']}")
    (EVENT / 'calibration.json').write_text(json.dumps(out, indent=1) + '\n')
    (ROOT / 'validation' / 'chelyabinsk-2013' / 'calibration-vs-cbet.json').write_text(json.dumps(vs_cbet, indent=1) + '\n')


if __name__ == '__main__':
    main()
