"""Monte Carlo of the three-station solution (Kamensk v2, Korkino v3, Tyumen v2) against CBET 3423.

Per draw every camera is re-fitted from perturbed evidence: line points 0.7 px, street bearings 0.7-1.0 deg,
landmark pixels 3 px, camera positions 8 m, SAM head points 1.5 px; Korkino's field of view is drawn from
N(79.5, 2.5) deg (speed agreement with Kamensk) and its unconstrained k1 from N(-0.15, 0.07). Usage: .venv/bin/python scripts/montecarlo3.py [draws]
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import EVENT, kamensk_camera_v2, korkino_camera, station, tyumen_camera  # noqa: E402
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
    rng = np.random.default_rng(1502)
    out = []
    for i in range(n):
        kc, kp = kamensk_camera_v2(rng, line_px_sigma=0.7, chapel_px_sigma=3.0, bearing_sigma=0.7, pos_sigma_m=8.0)
        cc, cp = korkino_camera(float(np.clip(rng.normal(79.5, 2.5), 72, 88)), rng, line_px_sigma=0.7, bearing_sigma=1.0,
                                k1=float(np.clip(rng.normal(-0.15, 0.07), -0.4, 0.0)))
        tc, tp = tyumen_camera(rng, line_px_sigma=0.7, vp_px_sigma=3.0, tower_px_sigma=2.0, bearing_sigma=0.7)
        try:
            sol = solve([station('chelyabinsk-2013-2', kc, kp, rng, 1.5), station('chelyabinsk-2013-10', cc, cp, rng, 1.5),
                         station('chelyabinsk-2013-48', tc, tp, rng, 1.5)])
        except GeometryError:
            continue
        _, at_flare = near(sol, flare['lat'], flare['lon'], flare['h_km'] * 1000)
        end_off, _ = near(sol, end['lat'], end['lon'], end['h_km'] * 1000)
        out.append({'azimuth': sol.azimuth, 'slope': sol.slope, 'flare_h_km': at_flare[2] / 1000,
                    'end_off_km': end_off / 1000, 'speed': sol.speed_kms})
        if (i + 1) % 10 == 0:
            print(f'{i + 1}/{n}', flush=True)
    ref = {'azimuth': truth['azimuth_deg'], 'slope': truth['slope_deg'], 'flare_h_km': flare['h_km'],
           'end_off_km': 0.0, 'speed': truth['apparent_radiant']['v_kms']}
    stats = {}
    for k in ref:
        v = np.array([o[k] for o in out if o[k] is not None])
        p = np.percentile(v, [2.5, 16, 50, 84, 97.5])
        stats[k] = {'median': round(float(p[2]), 2), '1sigma': [round(float(p[1]), 2), round(float(p[3]), 2)],
                    '2sigma': [round(float(p[0]), 2), round(float(p[4]), 2)], 'cbet': ref[k],
                    'cbet_within_1sigma': bool(p[1] <= ref[k] <= p[3]), 'cbet_within_2sigma': bool(p[0] <= ref[k] <= p[4])}
    (EVENT / 'montecarlo-2-10-48.json').write_text(json.dumps({'draws': len(out), 'stats': stats}, indent=1) + '\n')
    for k, s in stats.items():
        print(f"{k:11s} mediana {s['median']:7.2f}  1σ {s['1sigma']}  2σ {s['2sigma']}  CBET {s['cbet']}  1σ {s['cbet_within_1sigma']}  2σ {s['cbet_within_2sigma']}")


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 80)
