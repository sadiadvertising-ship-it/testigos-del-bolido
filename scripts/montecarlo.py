"""Monte Carlo of a Chelyabinsk solution (Kamensk v2, Korkino v4, Tyumen v2; any two or three).

Per draw every camera is re-fitted from perturbed evidence: line points 0.7 px, street bearings 0.7-1.0 deg,
landmark pixels 3 px, every camera position 8 m, SAM head points 1.5 px. Korkino's 480x360 frame cannot pin its field of
view, so it is drawn uniformly from 76 to 95 deg, a range that holds every value tried while calibrating it (79.5 from
speed agreement with Kamensk, 91.9 in an earlier fit); its unconstrained k1 is drawn from N(-0.15, 0.07). Each camera's
clock gets a scale error N(1, 0.01) and every timestamp +/- half a frame, so the speed carries the frame-timing doubt too.
Each draw's line (first and last observed point) is kept for the 3D viewer.
Writes events/chelyabinsk-2013/montecarlo-<stations>.json, which the agent's solve() reads for the speed range, and the
comparison with CBET 3423 to validation/chelyabinsk-2013/montecarlo-<stations>-vs-cbet.json, which it never reads.
Usage: .venv/bin/python scripts/montecarlo.py [draws, default 500] [station numbers, default 2 10 48]
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import EVENT, ROOT, TRUTH, kamensk_camera_v2, korkino_camera, station, tyumen_camera  # noqa: E402
from testigos.geo import to_ecef, to_geodetic  # noqa: E402
from testigos.solve import GeometryError, solve  # noqa: E402


def near(sol, lat, lon, h):
    q = to_ecef(lat, lon, h) - sol.point
    along = q @ sol.direction
    return float(np.linalg.norm(q - along * sol.direction)), to_geodetic(sol.point + along * sol.direction)


CAMERAS = {
    '2': lambda rng: kamensk_camera_v2(rng, line_px_sigma=0.7, chapel_px_sigma=3.0, bearing_sigma=0.7, pos_sigma_m=8.0),
    '10': lambda rng: korkino_camera(float(rng.uniform(76.0, 95.0)), rng, line_px_sigma=0.7, bearing_sigma=1.0,
                                     k1=float(np.clip(rng.normal(-0.15, 0.07), -0.4, 0.0)), pos_sigma_m=8.0),
    '48': lambda rng: tyumen_camera(rng, line_px_sigma=0.7, vp_px_sigma=3.0, tower_px_sigma=2.0, bearing_sigma=0.7, pos_sigma_m=8.0),
}


def main(n, nos):
    truth = json.loads(TRUTH.read_text())
    flare = next(p for p in truth['trajectory'] if p.get('note') == 'major flare')
    end = truth['trajectory'][-1]
    rng = np.random.default_rng(1502)
    out, lines = [], []
    for i in range(n):
        cams = [(no, *CAMERAS[no](rng)) for no in nos]
        try:
            sol = solve([station(f'chelyabinsk-2013-{no}', cam, pos, rng, 1.5, clock_sigma=0.01, jitter_frames=0.5)
                         for no, cam, pos in cams])
        except GeometryError:
            continue
        lines.append([round(sol.begin[0], 4), round(sol.begin[1], 4), round(sol.begin[2]), round(sol.end[0], 4), round(sol.end[1], 4), round(sol.end[2])])
        _, at_flare = near(sol, flare['lat'], flare['lon'], flare['h_km'] * 1000)
        end_off, _ = near(sol, end['lat'], end['lon'], end['h_km'] * 1000)
        out.append({'azimuth': sol.azimuth, 'slope': sol.slope, 'speed': sol.speed_kms, 'begin_h_km': sol.begin[2] / 1000,
                    'end_h_km': sol.end[2] / 1000, 'flare_h_km': at_flare[2] / 1000, 'end_off_km': end_off / 1000})
        if (i + 1) % 50 == 0:
            print(f'{i + 1}/{n}', flush=True)
    ref = {'azimuth': truth['azimuth_deg'], 'slope': truth['slope_deg'], 'flare_h_km': flare['h_km'],
           'end_off_km': 0.0, 'speed': truth['apparent_radiant']['v_kms']}
    stats, vs = {}, {}
    for k in out[0]:
        v = np.array([o[k] for o in out if o[k] is not None])
        p = np.percentile(v, [2.5, 16, 50, 84, 97.5])
        st = {'median': round(float(p[2]), 2), '1sigma': [round(float(p[1]), 2), round(float(p[3]), 2)],
              '2sigma': [round(float(p[0]), 2), round(float(p[4]), 2)]}
        if k not in ('flare_h_km', 'end_off_km'):  # those two are measured at CBET's points: validation only
            stats[k] = st
        if k in ref:
            vs[k] = {**st, 'cbet': ref[k], 'cbet_within_1sigma': bool(p[1] <= ref[k] <= p[3]),
                     'cbet_within_2sigma': bool(p[0] <= ref[k] <= p[4])}
    names = [f'chelyabinsk-2013-{no}' for no in nos]
    (EVENT / f"montecarlo-{'-'.join(nos)}.json").write_text(json.dumps(
        {'draws': len(out), 'stations': names, 'priors': __doc__.split('Writes')[0].strip(), 'stats': stats,
         'lines': {'columns': ['lat0', 'lon0', 'h0_m', 'lat1', 'lon1', 'h1_m'], 'rows': lines}}) + '\n')
    (ROOT / 'validation' / 'chelyabinsk-2013' / f"montecarlo-{'-'.join(nos)}-vs-cbet.json").write_text(json.dumps(
        {'draws': len(out), 'stations': names, 'stats': vs}, indent=1) + '\n')
    for k, s in vs.items():
        print(f"{k:11s} mediana {s['median']:7.2f}  1σ {s['1sigma']}  2σ {s['2sigma']}  CBET {s['cbet']}  1σ {s['cbet_within_1sigma']}  2σ {s['cbet_within_2sigma']}")


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 500, sys.argv[2:] or ['2', '10', '48'])
