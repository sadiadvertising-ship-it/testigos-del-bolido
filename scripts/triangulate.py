"""Triangulate Chelyabinsk from calibrated witness cameras and compare with the published CBET 3423 solution.

Usage: .venv/bin/python scripts/triangulate.py <catalog_no> <catalog_no> [...]
Reads each camera from events/chelyabinsk-2013/picks.json ('camera', or 'camera_v<N>' as the last resort)
and the SAM head points from out/sam/; writes out/chelyabinsk-2013/solution.json and prints the comparison.
"""
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from testigos.camera import Camera  # noqa: E402
from testigos.geo import to_ecef, to_geodetic  # noqa: E402
from testigos.solve import Station, solve  # noqa: E402

EVENT = ROOT / 'events' / 'chelyabinsk-2013'


def camera_of(entry):
    c = entry.get('camera') or entry[sorted(k for k in entry if k.startswith('camera_v'))[-1]]
    w, h = entry['image']
    return Camera(w, h, yaw=c['yaw'], pitch=c['pitch'], roll=c.get('roll', 0.0), hfov=c['hfov'], k1=c.get('k1', 0.0),
                  fisheye=entry.get('lens') == 'fisheye')


def station(no, picks):
    key = f'chelyabinsk-2013-{no}'
    entry = picks[key]
    cam = camera_of(entry)
    rows = json.loads((ROOT / 'out' / 'sam' / f'{key}.json').read_text())['rows']
    rows = [r for r in rows if r['centroid'] is not None and not r['dup']]
    rays = np.array([cam.unproject(r['centroid']) for r in rows])
    return Station(key, tuple(entry['camera_pos']), np.array([r['t'] for r in rows]), rays)


def line_distance(sol, geodetic):
    q = to_ecef(*geodetic) - sol.point
    along = q @ sol.direction
    closest = sol.point + along * sol.direction
    return float(np.linalg.norm(q - along * sol.direction)), to_geodetic(closest)


def main(nos):
    picks = json.loads((EVENT / 'picks.json').read_text())
    truth = json.loads((EVENT / 'truth.json').read_text())
    stations = [station(no, picks) for no in nos]
    sol = solve(stations)
    flare = next(p for p in truth['trajectory'] if p.get('note') == 'major flare')
    end = truth['trajectory'][-1]
    flare_off, flare_on_ours = line_distance(sol, (flare['lat'], flare['lon'], flare['h_km'] * 1000))
    end_dist = float(np.linalg.norm(to_ecef(*sol.end) - to_ecef(end['lat'], end['lon'], end['h_km'] * 1000)))
    end_off, _ = line_distance(sol, (end['lat'], end['lon'], end['h_km'] * 1000))
    cmp = {
        'stations': [s.name for s in stations], 'q_max_deg': round(sol.q_max, 1), 'warnings': sol.warnings,
        'residual_rms_deg': {k: round(v, 3) for k, v in sol.residual_rms_deg.items()},
        'azimuth_deg': [round(sol.azimuth, 2), truth['azimuth_deg']],
        'slope_deg': [round(sol.slope, 2), truth['slope_deg']],
        'speed_kms': [round(sol.speed_kms, 2) if sol.speed_kms else None, truth['apparent_radiant']['v_kms']],
        'speed_sigma_kms': round(sol.speed_sigma, 2) if sol.speed_sigma else None,
        'station_speeds_kms': {k: round(v[0], 2) for k, v in sol.station_speeds.items()},
        'flare_point_off_our_line_km': round(flare_off / 1000, 2),
        'our_height_near_flare_km': [round(flare_on_ours[2] / 1000, 2), flare['h_km']],
        'cbet_end_point_off_our_line_km': round(end_off / 1000, 2),
        'our_last_point_vs_cbet_end_km': round(end_dist / 1000, 2),
        'begin': [round(v, 4) for v in sol.begin[:2]] + [round(sol.begin[2] / 1000, 2)],
        'end': [round(v, 4) for v in sol.end[:2]] + [round(sol.end[2] / 1000, 2)],
    }
    gate = truth['gate_2026_10_28']
    cmp['gate'] = {
        'azimuth': abs(sol.azimuth - truth['azimuth_deg']) <= gate['azimuth_tol_deg'],
        'slope': abs(sol.slope - truth['slope_deg']) <= gate['slope_tol_deg'],
        'flare_height': abs(flare_on_ours[2] / 1000 - flare['h_km']) <= gate['flare_height_tol_km'],
        'end_point': end_off / 1000 <= gate['end_point_tol_km'],
    }
    out = ROOT / 'out' / 'chelyabinsk-2013'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'solution.json').write_text(json.dumps(cmp, indent=1) + '\n')
    print(json.dumps(cmp, indent=1))


if __name__ == '__main__':
    main([int(x) for x in sys.argv[1:]])
