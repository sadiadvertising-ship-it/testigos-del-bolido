"""Beloretsk's camera aimed with the fitted path: the yaw, pitch, roll and field of view that put the fitted line, flown on
Kamensk-Uralskiy's clock, under SAM's track in the frames where the car stands still (from 5.2 s of the trimmed clip),
together with the clock offset between the two videos. It uses the answer, so it is no check on it: it shows only where
the camera most likely pointed, and the viewer draws its lines of sight as such. The lens is taken as a plain dashcam
lens (k1 = 0), and the far ridges of the Urals along the horizon, which stand level in the still frames at about y = 492 px
(read by eye at x = 300 to 1200), are taken as 0.8 deg above the horizontal (SRTM ridges some 20 km off); without them
the roll is left to the track's slope. Writes validation/chelyabinsk-2013/after-run/aimed-with-path.json, which only scripts read.
Usage: .venv/bin/python scripts/aim_with_path.py
"""
import json
import pathlib
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from export_web import own_clock, sam_rows, solution, station  # noqa: E402
from stations import AFTER_RUN_DIR  # noqa: E402
from testigos.agent import Case  # noqa: E402
from testigos.camera import Camera  # noqa: E402
from testigos.geo import enu_basis, enu_to_azel, to_ecef  # noqa: E402

OUT = AFTER_RUN_DIR / 'aimed-with-path.json'
CLIP, STILL_FROM_S = '14', 5.2
GROUND_M = 532.0  # SRTM 30 m at the catalogue's position (OpenTopoData), the camera on the ground
RIDGE_Y, RIDGE_EL, RIDGE_X = 492.0, 0.8, (300.0, 750.0, 1200.0)  # the level far ridges in the still frames


def main():
    case = Case('chelyabinsk-2013')
    final = json.loads((case.dir / 'final_solution.json').read_text())['clips']
    sol, s0, _ = solution(case, final)
    k = station(case, '2')  # where the fireball was along the line at each instant of Kamensk-Uralskiy's clock
    _, s_k, _, shift = own_clock(sol, s0, k)
    tau_k = k.times - shift
    ev = next(c for c in case.event['clips'] if str(c['catalog_no']) == CLIP)
    pos = (ev['lat'], ev['lon'], GROUND_M)
    origin, basis = to_ecef(*pos), enu_basis(ev['lat'], ev['lon'])
    rows = [r for r in sam_rows(case, CLIP) if r['t'] >= STILL_FROM_S]
    px, t = np.array([r['centroid'] for r in rows], float), np.array([r['t'] for r in rows])
    w, h = ev['frame_px']

    def target(tau):  # unit ENU directions from the camera to the line, at Kamensk-Uralskiy's instants tau
        p = sol.point + np.interp(tau, tau_k, s_k)[:, None] * sol.direction
        v = (p - origin) @ basis.T
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def resid(x):
        cam = Camera(w, h, yaw=x[0], pitch=x[1], roll=x[2], hfov=x[3], k1=0.0)
        out = []
        for v, q in zip(target(t + x[4]), px):
            p = cam.project(v)
            out.extend(p - q if p is not None else (2000.0, 2000.0))
        for x_px in RIDGE_X:  # the ridges' elevation where the camera puts each of these pixels on the ridge line
            v = cam.unproject((x_px, RIDGE_Y))
            out.append((np.degrees(np.arcsin(v[2])) - RIDGE_EL) * cam.focal * np.pi / 180 * 3)
        return np.array(out)

    best = None
    for off in np.arange(tau_k.min() - t.min(), tau_k.max() - t.max() + 0.01, 0.5):  # the clock offset, by a coarse search
        mid = target(np.array([t.mean() + off]))[0]
        az, el = enu_to_azel(mid)
        for hfov in (50.0, 70.0, 90.0, 110.0):
            r = least_squares(resid, [az, el, 0.0, hfov, off], bounds=([-720, -60, -30, 30, -60], [720, 60, 30, 140, 60]))
            if best is None or r.cost < best.cost:
                best = r
    yaw, pitch, roll, hfov, off = best.x
    rms = float(np.sqrt(np.mean(best.fun[:-len(RIDGE_X)] ** 2) * 2))
    cam = Camera(w, h, yaw=yaw % 360, pitch=pitch, roll=roll, hfov=hfov, k1=0.0)
    entry = {'site': ev['site'], 'outcome': 'aimed',
             'how': 'aimed with the fitted path, not oriented: the yaw, pitch, roll and field of view (and the clock offset to '
                    "Kamensk-Uralskiy's video) that put the fitted line, flown on Kamensk-Uralskiy's clock, under SAM's track "
                    f'in the frames where the car stands still (from {STILL_FROM_S} s of the trimmed clip), with the far ridges '
                    f'level at y = {RIDGE_Y:.0f} px taken as {RIDGE_EL} deg up; a plain lens (k1 = 0) and the camera on the ground (SRTM). It uses the answer, so it checks nothing; it shows where '
                    'the camera most likely pointed (scripts/aim_with_path.py)',
             'camera_pos': [ev['lat'], ev['lon'], GROUND_M], 'image': [w, h], 'lens': 'pinhole',
             'camera': {'yaw': round(cam.yaw, 4), 'pitch': round(pitch, 4), 'roll': round(roll, 4), 'hfov': round(hfov, 3), 'k1': 0.0},
             'still_from_s': STILL_FROM_S, 'clock_offset_s': round(float(off), 3), 'rows': len(rows),
             'fit_rms_px': round(rms, 2)}
    OUT.write_text(json.dumps({'note': __doc__.split('Usage')[0].strip(), f'chelyabinsk-2013-{CLIP}': entry},
                              ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(entry, ensure_ascii=False)[:600])


if __name__ == '__main__':
    main()
