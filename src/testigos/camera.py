"""Pinhole camera with unknown pointing and field of view, calibrated from landmarks.

The camera looks along azimuth `yaw`, elevation `pitch`, rotated by `roll` about its axis.
Image x grows to the right and y grows down; the principal point is the image centre.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import least_squares

from .geo import azel_between, azel_to_enu, angle_between


@dataclass
class Camera:
    width: int
    height: int
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    hfov: float = 65.0
    k1: float = 0.0

    @property
    def focal(self):
        return (self.width / 2) / np.tan(np.radians(self.hfov) / 2)

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
        """ENU direction -> pixel (x, y), or None when it is behind the camera."""
        right, down, fwd = self.axes()
        z = np.dot(v_enu, fwd)
        if z <= 1e-9:
            return None
        xn, yn = np.dot(v_enu, right) / z, np.dot(v_enu, down) / z
        s = 1 + self.k1 * (xn * xn + yn * yn)
        return np.array([self.width / 2 + self.focal * xn * s, self.height / 2 + self.focal * yn * s])

    def unproject(self, px):
        """Pixel (x, y) -> unit ENU direction."""
        xd = (px[0] - self.width / 2) / self.focal
        yd = (px[1] - self.height / 2) / self.focal
        xn, yn = xd, yd
        for _ in range(8):
            s = 1 + self.k1 * (xn * xn + yn * yn)
            xn, yn = xd / s, yd / s
        right, down, fwd = self.axes()
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

    x0 = [getattr(cam0, n) for n in names]
    lo = [-np.inf, -89.0, -180.0] + ([] if fixed_hfov else [5.0]) + ([-0.5] if fit_k1 else [])
    hi = [np.inf, 89.0, 180.0] + ([] if fixed_hfov else [170.0]) + ([0.5] if fit_k1 else [])
    sol = least_squares(resid, x0, bounds=(lo, hi), loss='soft_l1', f_scale=3.0)
    return build(sol.x)


def _angular_errors(cam, azel, pixels):
    return [angle_between(cam.unproject(px), azel_to_enu(az, el)) for (az, el), px in zip(azel, pixels)]


def calibrate(width, height, cam_pos, landmarks, hfov_guess=65.0, fixed_hfov=None):
    """Solve yaw, pitch, roll and hfov (and k1 with 4+ landmarks) from landmark pixels.

    cam_pos is (lat, lon, h). landmarks is a list of ((lat, lon, h), (x, y)).
    With 3+ landmarks the leave-one-out error says how well an unseen point is predicted.
    """
    if len(landmarks) < 2:
        raise ValueError('need at least 2 landmarks')
    azel = [azel_between(cam_pos, p) for p, _ in landmarks]
    pixels = [np.asarray(px, float) for _, px in landmarks]
    seed = Camera(width, height, yaw=_circular_mean([a for a, _ in azel]),
                  pitch=float(np.mean([e for _, e in azel])), hfov=fixed_hfov or hfov_guess)
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
