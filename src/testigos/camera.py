"""Camera models with unknown pointing and field of view, calibrated from landmarks.

The camera looks along azimuth `yaw`, elevation `pitch`, rotated by `roll` about its axis.
Image x grows to the right and y grows down; the principal point is the image centre.
`fisheye=False` is a pinhole with radial distortion k1; `fisheye=True` is equidistant (r = f * angle),
which fits the circular security cameras.

A landmark is either a surveyed point ((lat, lon, h), pixel) or a pure direction (('azel', az, el), pixel):
directions (a distant peak, a road's vanishing point, the Moon) do not care where exactly the camera stood.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import least_squares

from .geo import angle_between, azel_between, azel_to_enu


@dataclass
class Camera:
    width: int
    height: int
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    hfov: float = 65.0
    k1: float = 0.0
    fisheye: bool = False

    @property
    def focal(self):
        half = np.radians(self.hfov) / 2
        return (self.width / 2) / (half if self.fisheye else np.tan(half))

    def axes(self):
        """Right, down and forward unit vectors in ENU."""
        y, p, r = np.radians([self.yaw, self.pitch, self.roll])
        fwd = np.array([np.cos(p) * np.sin(y), np.cos(p) * np.cos(y), np.sin(p)])
        right0 = np.array([np.cos(y), -np.sin(y), 0.0])
        up0 = np.cross(right0, fwd)
        right = np.cos(r) * right0 + np.sin(r) * up0
        up = -np.sin(r) * right0 + np.cos(r) * up0
        return right, -up, fwd

    def project(self, v_enu):
        """ENU direction -> pixel (x, y), or None when the camera cannot see it."""
        right, down, fwd = self.axes()
        x, y, z = np.dot(v_enu, right), np.dot(v_enu, down), np.dot(v_enu, fwd)
        if self.fisheye:
            theta = np.arctan2(np.hypot(x, y), z)
            if theta > np.radians(100):
                return None
            r = self.focal * theta * (1 + self.k1 * theta * theta)
            phi = np.arctan2(y, x)
            return np.array([self.width / 2 + r * np.cos(phi), self.height / 2 + r * np.sin(phi)])
        if z <= 1e-9:
            return None
        xn, yn = x / z, y / z
        s = 1 + self.k1 * (xn * xn + yn * yn)
        return np.array([self.width / 2 + self.focal * xn * s, self.height / 2 + self.focal * yn * s])

    def unproject(self, px):
        """Pixel (x, y) -> unit ENU direction."""
        dx = (px[0] - self.width / 2) / self.focal
        dy = (px[1] - self.height / 2) / self.focal
        right, down, fwd = self.axes()
        if self.fisheye:
            rd = np.hypot(dx, dy)
            theta = rd
            for _ in range(12):
                theta = rd / (1 + self.k1 * theta * theta)
            phi = np.arctan2(dy, dx)
            v = np.sin(theta) * (np.cos(phi) * right + np.sin(phi) * down) + np.cos(theta) * fwd
            return v / np.linalg.norm(v)
        xn, yn = dx, dy
        for _ in range(8):
            s = 1 + self.k1 * (xn * xn + yn * yn)
            xn, yn = dx / s, dy / s
        v = xn * right + yn * down + fwd
        return v / np.linalg.norm(v)

    def project_azel(self, az, el):
        return self.project(azel_to_enu(az, el))


@dataclass
class Calibration:
    camera: Camera
    rms_deg: float
    loo_deg: float | None
    residuals_deg: list


def _circular_mean(deg):
    r = np.radians(deg)
    return float(np.degrees(np.arctan2(np.mean(np.sin(r)), np.mean(np.cos(r)))) % 360)


def landmark_azel(cam_pos, where):
    """(az, el) of a landmark that is either a surveyed point or an ('azel', az, el) direction."""
    if isinstance(where, (tuple, list)) and len(where) == 3 and where[0] == 'azel':
        return float(where[1]), float(where[2])
    return azel_between(cam_pos, where)


def _fit(cam0, azel, pixels, fit_k1, fixed_hfov):
    names = ['yaw', 'pitch', 'roll'] + ([] if fixed_hfov else ['hfov']) + (['k1'] if fit_k1 else [])

    def build(x):
        return replace(cam0, **dict(zip(names, x)))

    def resid(x):
        cam = build(x)
        out = []
        for (az, el), px in zip(azel, pixels):
            p = cam.project_azel(az, el)
            out.extend((p - px) if p is not None else (1e4, 1e4))
        return np.array(out)

    top = 200.0 if cam0.fisheye else 170.0
    x0 = [getattr(cam0, n) for n in names]
    lo = [-np.inf, -89.0, -180.0] + ([] if fixed_hfov else [5.0]) + ([-0.5] if fit_k1 else [])
    hi = [np.inf, 89.0, 180.0] + ([] if fixed_hfov else [top]) + ([0.5] if fit_k1 else [])
    sol = least_squares(resid, x0, bounds=(lo, hi), loss='soft_l1', f_scale=3.0)
    return build(sol.x)


def _angular_errors(cam, azel, pixels):
    return [angle_between(cam.unproject(px), azel_to_enu(az, el)) for (az, el), px in zip(azel, pixels)]


def _wrap(deg):
    return (deg + 180.0) % 360.0 - 180.0


def fit(seed, cam_pos, points=(), x_only=(), plumb=(), horizon=(), horizon_el=0.0,
        free=('yaw', 'pitch', 'roll', 'hfov', 'k1')):
    """Least-squares camera fit from mixed evidence; returns (camera, report).

    points: [(where, (x, y))] landmarks or directions with a full pixel position;
    x_only: [(where, x)] objects whose height is unknown, so only their horizontal pixel counts;
    plumb:  [[(x, y), ...]] pixels along objects that are vertical in the world (poles, building corners).
            A vertical line keeps one azimuth seen from the camera, so the spread of azimuths along it
            measures roll and lens distortion.
    horizon: [(x, y)] pixels on a flat, distant horizon, all at elevation horizon_el.
    All residuals are in pixels so the groups weigh alike.
    """
    hz = [np.asarray(p, float) for p in horizon]
    pts_azel = [(landmark_azel(cam_pos, w), np.asarray(px, float)) for w, px in points]
    xo_azel = [(landmark_azel(cam_pos, w), float(x)) for w, x in x_only]
    lines = [np.asarray(l, float) for l in plumb if len(l) >= 2]
    lo = {'yaw': -np.inf, 'pitch': -89.0, 'roll': -45.0, 'hfov': 5.0, 'k1': -0.6}
    hi = {'yaw': np.inf, 'pitch': 89.0, 'roll': 45.0, 'hfov': 200.0 if seed.fisheye else 170.0, 'k1': 0.6}

    def build(x):
        return replace(seed, **dict(zip(free, x)))

    def groups(cam):
        g = {'points': [], 'x_only': [], 'plumb': [], 'horizon': []}
        for p in hz:
            r = cam.unproject(p)
            g['horizon'].append((np.arcsin(np.clip(r[2], -1, 1)) - np.radians(horizon_el)) * cam.focal)
        for (az, el), px in pts_azel:
            p = cam.project_azel(az, el)
            g['points'].extend((p - px) if p is not None else (1e4, 1e4))
        for (az, el), x in xo_azel:
            p = cam.project_azel(az, el)
            g['x_only'].append((p[0] - x) if p is not None else 1e4)
        for line in lines:
            rays = [cam.unproject(p) for p in line]
            az = np.array([np.degrees(np.arctan2(r[0], r[1])) for r in rays])
            el = np.array([np.arcsin(np.clip(r[2], -1, 1)) for r in rays])
            mean = np.degrees(np.arctan2(np.mean(np.sin(np.radians(az))), np.mean(np.cos(np.radians(az)))))
            g['plumb'].extend(np.radians(_wrap(az - mean)) * np.cos(el) * cam.focal)
        return g

    def resid(x):
        g = groups(build(x))
        return np.array(g['points'] + g['x_only'] + g['plumb'] + g['horizon'])

    sol = least_squares(resid, [getattr(seed, n) for n in free],
                        bounds=([lo[n] for n in free], [hi[n] for n in free]), loss='soft_l1', f_scale=3.0)
    cam = build(sol.x)
    g = groups(cam)
    report = {k: {'n': len(v), 'rms_px': float(np.sqrt(np.mean(np.square(v)))) if v else None,
                  'rms_deg': float(np.degrees(np.sqrt(np.mean(np.square(v))) / cam.focal)) if v else None}
              for k, v in g.items()}
    return cam, report


def calibrate(width, height, cam_pos, landmarks, hfov_guess=65.0, fixed_hfov=None, fisheye=False, seed=None):
    """Solve yaw, pitch, roll and hfov (and k1 with 4+ landmarks) from landmark pixels.

    cam_pos is (lat, lon, h). landmarks is a list of (where, (x, y)); see landmark_azel for `where`.
    With 3+ landmarks the leave-one-out error says how well an unseen point is predicted.
    `seed` is an optional Camera to start from (for example from a skyline fit).
    """
    if len(landmarks) < 2:
        raise ValueError('need at least 2 landmarks')
    azel = [landmark_azel(cam_pos, w) for w, _ in landmarks]
    pixels = [np.asarray(px, float) for _, px in landmarks]
    if seed is None:
        seed = Camera(width, height, yaw=_circular_mean([a for a, _ in azel]),
                      pitch=float(np.mean([e for _, e in azel])), hfov=fixed_hfov or hfov_guess, fisheye=fisheye)
    fit_k1 = len(landmarks) >= 4
    cam = _fit(seed, azel, pixels, fit_k1, fixed_hfov is not None)
    errs = _angular_errors(cam, azel, pixels)
    loo = None
    if len(landmarks) >= 3:
        worst = []
        for i in range(len(landmarks)):
            keep = [j for j in range(len(landmarks)) if j != i]
            c = _fit(seed, [azel[j] for j in keep], [pixels[j] for j in keep],
                     fit_k1 and len(keep) >= 4, fixed_hfov is not None)
            worst.append(_angular_errors(c, [azel[i]], [pixels[i]])[0])
        loo = float(max(worst))
    return Calibration(cam, float(np.sqrt(np.mean(np.square(errs)))), loo, errs)
