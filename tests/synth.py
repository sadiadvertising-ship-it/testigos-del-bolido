"""A synthetic fireball on the published Chelyabinsk end points (CBET 3423), seen from made-up stations."""
import numpy as np

from testigos.camera import Camera, calibrate
from testigos.geo import azel_between, azel_to_enu, enu_basis, to_ecef, to_geodetic
from testigos.solve import Station

BEGIN = (54.508, 64.266, 91830.0)
END = (54.922, 60.606, 14940.0)
DURATION = 16.2
STATIONS = {'chelyabinsk': (55.16, 61.40, 230.0), 'south': (54.40, 61.25, 200.0), 'northeast': (55.80, 62.00, 200.0)}


def path(n=80):
    b, e = to_ecef(*BEGIN), to_ecef(*END)
    t = np.linspace(0.0, DURATION, n)
    return t, b + (e - b) * (t / DURATION)[:, None]


def true_speed_kms():
    return float(np.linalg.norm(to_ecef(*END) - to_ecef(*BEGIN)) / DURATION / 1000)


def true_motion_enu():
    d = to_ecef(*END) - to_ecef(*BEGIN)
    return enu_basis(END[0], END[1]) @ (d / np.linalg.norm(d))


def rays_from(pos, pts, noise_deg=0.0, rng=None, min_el=2.0):
    v = (pts - to_ecef(*pos)) @ enu_basis(pos[0], pos[1]).T
    v /= np.linalg.norm(v, axis=1)[:, None]
    if noise_deg:
        v = v + rng.normal(0, np.radians(noise_deg), v.shape)
        v /= np.linalg.norm(v, axis=1)[:, None]
    return v[:, 2] > np.sin(np.radians(min_el)), v


def exact_station(name, t, pts, **kw):
    keep, v = rays_from(STATIONS[name], pts, **kw)
    return Station(name, STATIONS[name], t[keep], v[keep])


def landmark(pos, az, el, range_km):
    target = to_ecef(*pos) + range_km * 1000 * (azel_to_enu(az, el) @ enu_basis(pos[0], pos[1]))
    return to_geodetic(target)


def filmed_station(name, yaw, pitch, roll, hfov, t, pts, rng, px_noise=1.5):
    """Film the synthetic path with a true camera, calibrate a guessed one from 4 landmarks, unproject."""
    pos = STATIONS[name]
    true_cam = Camera(1280, 720, yaw, pitch, roll, hfov)
    lms = []
    for daz, el, km in [(-25, 1.0, 4), (-8, 2.5, 9), (12, 0.8, 6), (28, 1.8, 12)]:
        ll = landmark(pos, yaw + daz, el, km)
        lms.append((ll, true_cam.project_azel(*azel_between(pos, ll)) + rng.normal(0, px_noise, 2)))
    cal = calibrate(1280, 720, pos, lms, hfov_guess=70.0)
    _, v = rays_from(pos, pts)
    times, rays = [], []
    for ti, vi in zip(t, v):
        px = true_cam.project(vi)
        if px is None or not (0 <= px[0] < 1280 and 0 <= px[1] < 720):
            continue
        rays.append(cal.camera.unproject(px + rng.normal(0, px_noise, 2)))
        times.append(ti)
    return Station(name, pos, np.array(times), np.array(rays)), cal


def distance_to_line(sol, geodetic):
    q = to_ecef(*geodetic) - sol.point
    return float(np.linalg.norm(q - (q @ sol.direction) * sol.direction))
