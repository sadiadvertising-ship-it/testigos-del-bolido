"""Shared builders for the Chelyabinsk stations, so the Monte Carlo can rebuild them from perturbed inputs."""
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from testigos.camera import Camera, calibrate, fit  # noqa: E402
from testigos.solve import Station  # noqa: E402

EVENT = ROOT / 'events' / 'chelyabinsk-2013'
PICKS = json.loads((EVENT / 'picks.json').read_text())
LINES_10 = json.loads((EVENT / 'lines-10.json').read_text())


def rows(key):
    return [r for r in json.loads((ROOT / 'out' / 'sam' / f'{key}.json').read_text())['rows']
            if r['centroid'] is not None and not r['dup']]


def station(key, cam, pos, rng=None, px_sigma=0.0):
    rs = rows(key)
    px = np.array([r['centroid'] for r in rs], float)
    if rng is not None and px_sigma:
        px = px + rng.normal(0, px_sigma, px.shape)
    return Station(key, tuple(pos), np.array([r['t'] for r in rs]), np.array([cam.unproject(p) for p in px]))


def kamensk_camera(rng=None, vp_px_sigma=0.0, chapel_px_sigma=0.0, bearing_sigma=0.0, pos_sigma_m=0.0):
    e = PICKS['chelyabinsk-2013-2']
    lat, lon, h = e['camera_pos']
    vp, chapel = e['landmarks']
    vp_px, ch_px = np.array(vp['px'], float), np.array(chapel['px'], float)
    bearing = vp['azel'][0]
    if rng is not None:
        vp_px = vp_px + rng.normal(0, vp_px_sigma, 2)
        ch_px = ch_px + rng.normal(0, chapel_px_sigma, 2)
        bearing = bearing + rng.normal(0, bearing_sigma)
        dn, de = rng.normal(0, pos_sigma_m, 2)
        lat, lon = lat + dn / 111320, lon + de / (111320 * np.cos(np.radians(lat)))
    pos = (lat, lon, h)
    cal = calibrate(1280, 720, pos, [(('azel', bearing, 0.0), vp_px), (tuple(chapel['pos']), ch_px)], hfov_guess=70.0)
    return cal.camera, pos


def korkino_camera(hfov, rng=None, line_px_sigma=0.0, bearing_sigma=0.0):
    e = PICKS['chelyabinsk-2013-10']
    bearing = e['alley_bearing_deg'] + (rng.normal(0, bearing_sigma) if rng is not None else 0.0)
    par, plumb, straight = [], [], []
    for k in ('a', 'b'):
        for l in LINES_10[k]['lines']:
            if 'pole' in l['name']:
                continue
            pts = np.array(l['points'], float)
            if rng is not None and line_px_sigma:
                pts = pts + rng.normal(0, line_px_sigma, pts.shape)
            if l['kind'] == 'along_alley':
                par.append(((bearing, 0.0), pts))
            elif l['kind'] == 'vertical':
                plumb.append(pts)
            else:
                straight.append(pts)
    pos = tuple(e['camera_pos'])
    seed = Camera(480, 360, yaw=bearing, pitch=1.0, roll=0.0, hfov=hfov, k1=-0.09)
    cam, _ = fit(seed, pos, plumb=plumb, straight=straight, parallel=par, free=('yaw', 'pitch', 'roll', 'k1'))
    return cam, pos
