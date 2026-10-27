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
TRUTH = ROOT / 'validation' / 'chelyabinsk-2013' / 'truth.json'  # published answer: scripts only, never the agent
PICKS = json.loads((EVENT / 'picks.json').read_text())
LINES_10 = json.loads((EVENT / 'lines-10.json').read_text())


def rows(key):
    return [r for r in json.loads((ROOT / 'out' / 'sam' / f'{key}.json').read_text())['rows']
            if r['centroid'] is not None and not r['dup']]


def station(key, cam, pos, rng=None, px_sigma=0.0, clock_sigma=0.0, jitter_frames=0.0):
    """A station from the SAM head points; with an rng, pixels get Gaussian noise and the clock a scale error
    N(1, clock_sigma) plus a uniform +/- jitter_frames error on every timestamp."""
    rs = rows(key)
    px = np.array([r['centroid'] for r in rs], float)
    t = np.array([r['t'] for r in rs], float)
    if rng is not None and px_sigma:
        px = px + rng.normal(0, px_sigma, px.shape)
    if rng is not None and (clock_sigma or jitter_frames):
        frame = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
        t = t * rng.normal(1.0, clock_sigma) + rng.uniform(-jitter_frames, jitter_frames, len(t)) * frame
    return Station(key, tuple(pos), t, np.array([cam.unproject(p) for p in px]))


def _moved(pos, rng, sigma_m):
    """The camera position shifted by a Gaussian sigma_m metres north and east."""
    if rng is None or not sigma_m:
        return tuple(pos)
    lat, lon, h = pos
    dn, de = rng.normal(0, sigma_m, 2)
    return (lat + dn / 111320, lon + de / (111320 * np.cos(np.radians(lat))), h)


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


def korkino_camera(hfov, rng=None, line_px_sigma=0.0, bearing_sigma=0.0, k1=-0.15, with_report=False, pos_sigma_m=0.0):
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
    pos = _moved(e['camera_pos'], rng, pos_sigma_m)
    # The small 480x360 frame does not pin the distortion: 0.7 px of jitter sends a free k1 from -0.2 to
    # either bound. So k1 is a nuisance with a typical wide-dashcam value, varied in the Monte Carlo,
    # and the lines fix only the pointing.
    seed = Camera(480, 360, yaw=bearing, pitch=1.0, roll=0.0, hfov=hfov, k1=k1)
    cam, report = fit(seed, pos, plumb=plumb, straight=straight, parallel=par, free=('yaw', 'pitch', 'roll'))
    return (cam, pos, report) if with_report else (cam, pos)


LINES_2 = json.loads((EVENT / 'lines-2.json').read_text())
PLUMB_48 = json.loads((EVENT / 'plumb-48.json').read_text())


def kamensk_camera_v2(rng=None, line_px_sigma=0.0, chapel_px_sigma=0.0, bearing_sigma=0.0, pos_sigma_m=0.0, with_report=False):
    """Kamensk from annotated lines (avenue and cross street bearings from OSM) plus the chapel."""
    e = PICKS['chelyabinsk-2013-2']
    lat, lon, h = e['camera_pos']
    avenue, cross = 182.5, 271.8
    ch_px = np.array([1132.0, 345.0])
    if rng is not None:
        avenue, cross = avenue + rng.normal(0, bearing_sigma), cross + rng.normal(0, bearing_sigma)
        ch_px = ch_px + rng.normal(0, chapel_px_sigma, 2)
        dn, de = rng.normal(0, pos_sigma_m, 2)
        lat, lon = lat + dn / 111320, lon + de / (111320 * np.cos(np.radians(lat)))

    def jitter(pts):
        pts = np.array(pts, float)
        return pts + rng.normal(0, line_px_sigma, pts.shape) if rng is not None and line_px_sigma else pts

    plumb = [jitter(l['points']) for k in ('a', 'b') for l in LINES_2[k]['lines'] if l['kind'] == 'vertical']
    par = [((avenue, 0.0), jitter(l['points'])) for l in LINES_2['b']['lines'] if l['kind'] == 'along_avenue']
    par += [((cross, 0.0), jitter(l['points'])) for l in LINES_2['a']['lines'] if l['kind'] == 'along_cross_street']
    pos = (lat, lon, h)
    c = e['camera']
    seed = Camera(1280, 720, yaw=c['yaw'], pitch=c['pitch'], roll=c['roll'], hfov=c['hfov'], k1=c['k1'])
    cam, report = fit(seed, pos, plumb=plumb, parallel=par, points=[((56.4142, 61.917691, 0.0), ch_px)], bounds={'k1': (-0.45, 0.0)})
    return (cam, pos, report) if with_report else (cam, pos)


def tyumen_camera(rng=None, line_px_sigma=0.0, vp_px_sigma=0.0, tower_px_sigma=0.0, bearing_sigma=0.0, with_report=False,
                  pos_sigma_m=0.0):
    e = PICKS['chelyabinsk-2013-48']
    pos = _moved(e['camera_pos'], rng, pos_sigma_m)
    vp_az, vp_px = 235.9, np.array([595.0, 345.0])
    tower_x = 1258.2
    if rng is not None:
        vp_az += rng.normal(0, bearing_sigma)
        vp_px = vp_px + rng.normal(0, vp_px_sigma, 2)
        tower_x += rng.normal(0, tower_px_sigma)
    lines = []
    for k in ('a', 'b'):
        for l in PLUMB_48[k]['lines']:
            pts = np.array(l['points'], float)
            if rng is not None and line_px_sigma:
                pts = pts + rng.normal(0, line_px_sigma, pts.shape)
            lines.append(pts)
    c = e['camera']
    seed = Camera(1280, 720, yaw=c['yaw'], pitch=c['pitch'], roll=c['roll'], hfov=c['hfov'], k1=c['k1'])
    cam, report = fit(seed, pos, points=[(('azel', vp_az, 0.0), vp_px)], x_only=[((57.2026, 65.6031095, 38.0), tower_x)], plumb=lines)
    return (cam, pos, report) if with_report else (cam, pos)
