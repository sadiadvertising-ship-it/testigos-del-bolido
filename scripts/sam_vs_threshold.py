"""SAM 3.1 against a brightness threshold: is SAM needed when the fireball is the brightest thing in the sky?

Every tracked frame in out/sam/ holds two measurements of the fireball: SAM 3.1's head point ('centroid', from the box
SAM tracked with the phrase "bright light") and the numpy baseline that runs alongside ('blob': the largest saturated
blob, kept only if it moves smoothly). This script feeds both, on the same frames and through the same cameras, to the
same solver, and measures how far each one's rays sit from the plane that CBET 3423's published path makes with each
camera. The baseline is a plain threshold, not a tuned classical tracker; it shows what SAM's choice of object buys.
CBET is used only to grade, so the output goes to validation/chelyabinsk-2013/sam-vs-threshold.json.
Usage: .venv/bin/python scripts/sam_vs_threshold.py
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import ROOT, TRUTH  # noqa: E402
from testigos.agent import Case  # noqa: E402
from testigos.camera import Camera  # noqa: E402
from testigos.geo import enu_basis, to_ecef  # noqa: E402
from testigos.solve import GeometryError, Station, solve  # noqa: E402

OUT = ROOT / 'validation' / 'chelyabinsk-2013' / 'sam-vs-threshold.json'
NAMES = {'2': 'Kamensk-Uralskiy', '10': 'Korkino', '48': 'Tyumen'}


def stations(case, clips, field):
    out = []
    for clip in clips:
        e = case.picks[case.key(clip)]
        c, (w, h) = e['camera'], e['image']
        cam = Camera(w, h, yaw=c['yaw'], pitch=c['pitch'], roll=c.get('roll', 0.0), hfov=c['hfov'], k1=c.get('k1', 0.0),
                     fisheye=e.get('lens') == 'fisheye')
        rows = [r for r in json.loads((ROOT / 'out' / 'sam' / f'{case.key(clip)}.json').read_text())['rows']
                if r['centroid'] is not None and r.get('blob') is not None and not r['dup']]  # the same frames for both
        out.append(Station(clip, tuple(e['camera_pos']), np.array([r['t'] for r in rows]),
                           np.array([cam.unproject(r[field]) for r in rows])))
    return out


def off_plane(st):
    """Angle of each ray from the plane through the camera and CBET's published path, in degrees."""
    path = json.loads(TRUTH.read_text())['trajectory']
    a, b = (to_ecef(p['lat'], p['lon'], p['h_km'] * 1000) for p in (path[0], path[-1]))
    o = to_ecef(*st.pos)
    n = np.cross(a - o, b - o)
    n /= np.linalg.norm(n)
    ang = np.abs(np.degrees(np.arcsin(np.clip((st.rays_enu @ enu_basis(st.pos[0], st.pos[1])) @ n, -1, 1))))
    return {'rays': int(len(ang)), 'median_deg': round(float(np.median(ang)), 2), 'p84_deg': round(float(np.percentile(ang, 84)), 2)}


def summary(sol):
    return {'azimuth_deg': round(sol.azimuth, 1), 'slope_deg': round(sol.slope, 1),
            'speed_kms': round(sol.speed_kms, 2) if sol.speed_kms is not None else None,
            'speed_per_camera_kms': {k: round(v, 2) for k, (v, _) in sol.station_speeds.items()}}


def main():
    case = Case('chelyabinsk-2013')
    truth = json.loads(TRUTH.read_text())
    out = {'what': __doc__.split('Usage')[0].strip(), 'cbet': {'azimuth_deg': truth['azimuth_deg'], 'slope_deg': truth['slope_deg']},
           'off_cbet_plane': {}, 'solutions': {}}
    for clip in ('2', '10', '48'):
        sam, blob = (stations(case, [clip], f)[0] for f in ('centroid', 'blob'))
        out['off_cbet_plane'][NAMES[clip]] = {'sam': off_plane(sam), 'threshold': off_plane(blob)}
    for clips in (['2', '10'], ['2', '10', '48']):
        row = {}
        for label, field in (('sam', 'centroid'), ('threshold', 'blob')):
            try:
                row[label] = summary(solve(stations(case, clips, field)))
            except GeometryError as exc:
                row[label] = {'error': str(exc)}
        out['solutions']['+'.join(clips)] = row
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    for cam, r in out['off_cbet_plane'].items():
        print(f"{cam:17s} off CBET's plane: SAM median {r['sam']['median_deg']}° (p84 {r['sam']['p84_deg']}°), "
              f"threshold {r['threshold']['median_deg']}° (p84 {r['threshold']['p84_deg']}°)")
    for clips, r in out['solutions'].items():
        print(f'{clips:8s} SAM {r["sam"]}\n{"":8s} threshold {r["threshold"]}')


if __name__ == '__main__':
    main()
