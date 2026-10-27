"""Monte Carlo uncertainty of the Kamensk + Korkino trajectory, compared with CBET 3423.

Every draw re-calibrates both cameras from perturbed inputs and re-solves the path:
  Kamensk: vanishing-point and chapel pixels (3 px), avenue bearing (0.7 deg), camera position (8 m);
  Korkino: field of view (self-calibration is flat between 75 and 110 deg: normal 91.9 +/- 7, clipped),
           alley bearing (1 deg), annotated line points (0.7 px);
  both:    SAM head points (1.5 px).
Usage: .venv/bin/python scripts/montecarlo.py [draws]
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import EVENT, kamensk_camera, korkino_camera, station  # noqa: E402
from testigos.geo import to_ecef, to_geodetic  # noqa: E402
from testigos.solve import GeometryError, solve  # noqa: E402


def near(sol, lat, lon, h):
    q = to_ecef(lat, lon, h) - sol.point
    along = q @ sol.direction
    return float(np.linalg.norm(q - along * sol.direction)), to_geodetic(sol.point + along * sol.direction)


def main(n):
    truth = json.loads((EVENT / 'truth.json').read_text())
    flare = next(p for p in truth['trajectory'] if p.get('note') == 'major flare')
    end = truth['trajectory'][-1]
    rng = np.random.default_rng(2013)
    out = []
    for i in range(n):
        kc, kp = kamensk_camera(rng, vp_px_sigma=3.0, chapel_px_sigma=3.0, bearing_sigma=0.7, pos_sigma_m=8.0)
        hfov = float(np.clip(rng.normal(91.9, 7.0), 75.0, 110.0))
        cc, cp = korkino_camera(hfov, rng, line_px_sigma=0.7, bearing_sigma=1.0)
        try:
            sol = solve([station('chelyabinsk-2013-2', kc, kp, rng, 1.5), station('chelyabinsk-2013-10', cc, cp, rng, 1.5)])
        except GeometryError:
            continue
        _, at_flare = near(sol, flare['lat'], flare['lon'], flare['h_km'] * 1000)
        end_off, _ = near(sol, end['lat'], end['lon'], end['h_km'] * 1000)
        out.append({'azimuth': sol.azimuth, 'slope': sol.slope, 'flare_h_km': at_flare[2] / 1000,
                    'end_off_km': end_off / 1000, 'speed': sol.speed_kms, 'hfov_korkino': hfov})
        if (i + 1) % 20 == 0:
            print(f'{i + 1}/{n}', flush=True)
    keys = ['azimuth', 'slope', 'flare_h_km', 'end_off_km', 'speed']
    ref = {'azimuth': truth['azimuth_deg'], 'slope': truth['slope_deg'], 'flare_h_km': flare['h_km'],
           'end_off_km': 0.0, 'speed': truth['apparent_radiant']['v_kms']}
    stats = {}
    for k in keys:
        v = np.array([o[k] for o in out if o[k] is not None])
        p = np.percentile(v, [2.5, 16, 50, 84, 97.5])
        stats[k] = {'median': round(float(p[2]), 2), '1sigma': [round(float(p[1]), 2), round(float(p[3]), 2)],
                    '2sigma': [round(float(p[0]), 2), round(float(p[4]), 2)], 'cbet': ref[k],
                    'cbet_within_1sigma': bool(p[1] <= ref[k] <= p[3]), 'cbet_within_2sigma': bool(p[0] <= ref[k] <= p[4])}
    result = {'draws': len(out), 'stations': ['chelyabinsk-2013-2', 'chelyabinsk-2013-10'], 'stats': stats,
              'note': 'end_off_km is the distance from the CBET end point to our line; its CBET value is 0 by definition'}
    (EVENT / 'montecarlo-2-10.json').write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
