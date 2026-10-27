"""Triangulate a straight fireball path from two or more calibrated cameras.

Each camera's lines of sight to the fireball span a plane through the camera (Ceplecha 1987).
The best-converging pair of planes gives a first line; least squares over every ray refines it
(Borovicka 1990). No clock sync between videos is needed: speeds are fitted per camera.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .geo import enu_basis, enu_to_azel, to_ecef, to_geodetic


class GeometryError(ValueError):
    pass


@dataclass
class Station:
    name: str
    pos: tuple  # (lat, lon, h_m)
    times: np.ndarray  # seconds on this video's own clock
    rays_enu: np.ndarray  # N x 3 unit lines of sight in this station's ENU frame

    @property
    def origin(self):
        return to_ecef(*self.pos)

    @property
    def rays(self):
        return np.asarray(self.rays_enu, float) @ enu_basis(self.pos[0], self.pos[1])


@dataclass
class Solution:
    point: np.ndarray  # ECEF point on the path
    direction: np.ndarray  # ECEF unit vector along the motion
    begin: tuple  # (lat, lon, h_m) of the first observed point
    end: tuple
    azimuth: float  # direction of motion at the end point, clockwise from north
    slope: float  # descent angle below the horizontal at the end point
    radiant_azel: tuple  # where it came from, seen from the end point
    speed_kms: float | None
    speed_sigma: float | None
    station_speeds: dict
    q_max: float  # largest angle between two stations' planes
    residual_rms_deg: dict
    warnings: list = field(default_factory=list)
    left_out: tuple = ()  # cameras whose clock solve() distrusted and kept out of the speed
    speed_sigma_formal: float | None = None  # inverse-variance error of the combined speed
    speed_spread: float | None = None  # spread between the cameras' speeds over sqrt(n)

    def at_time(self, station, i):
        """Geodetic point on the path for observation i of a station."""
        s, _, q, _ = _closest(self.point, self.direction, station.origin, station.rays[i])
        return to_geodetic(q)


def plane_normal(rays, iterations=3, floor_deg=0.2):
    """Normal of the plane through the camera that best contains the rays.

    Rays more than 3 robust sigmas (or floor_deg) off the plane are dropped and the plane refitted:
    flare frames, where the glow centre sits off the head, must not tilt the plane.
    """
    rays = np.asarray(rays, float)
    keep = np.ones(len(rays), bool)
    n = np.linalg.svd(rays)[2][-1]
    for _ in range(iterations):
        off = np.abs(rays @ n)
        mad = np.median(off[keep]) * 1.4826
        new = off <= max(3 * mad, np.sin(np.radians(floor_deg)))
        if new.sum() < 3 or (new == keep).all():
            break
        keep = new
        n = np.linalg.svd(rays[keep])[2][-1]
    return n


def convergence(n1, n2):
    """Angle between two planes, 0-90 degrees."""
    return float(np.degrees(np.arccos(min(1.0, abs(float(np.dot(n1, n2)))))))


def _closest(p, d, c, r):
    """Closest points between the line p + s*d and the ray c + t*r (unit d and r)."""
    w = p - c
    b = float(d @ r)
    den = max(1 - b * b, 1e-12)
    s = (b * (r @ w) - (d @ w)) / den
    t = ((r @ w) - b * (d @ w)) / den
    return s, t, p + s * d, c + t * r


def _perpendiculars(d):
    a = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(d, a)
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(d, e1)


def intersect_planes(st1, st2):
    n1, n2 = plane_normal(st1.rays), plane_normal(st2.rays)
    d = np.cross(n1, n2)
    d /= np.linalg.norm(d)
    c1, c2 = st1.origin, st2.origin
    p = np.linalg.solve(np.array([n1, n2, d]), np.array([n1 @ c1, n2 @ c2, d @ (c1 + c2) / 2]))
    return p, d


def _ray_residuals(p, d, stations):
    out = []
    for st in stations:
        c = st.origin
        for r in st.rays:
            _, _, q, _ = _closest(p, d, c, r)
            v = q - c
            along = float(v @ r)
            perp = v - along * r
            out.append(perp / max(along, 1.0))
    return np.concatenate(out) if out else np.zeros(0)


def _fit_speed(times, s, frac=0.6):
    """Linear speed (m/s) over the first `frac` of the visible path; returns (v, sigma) or None."""
    t = np.asarray(times, float)
    keep = t <= t.min() + frac * (t.max() - t.min())
    if keep.sum() < 3:
        keep = np.ones_like(t, bool)
    if keep.sum() < 3:
        return None
    coef, cov = np.polyfit(t[keep], np.asarray(s)[keep], 1, cov=True)
    return float(coef[0]), float(np.sqrt(max(cov[0, 0], 0.0)))


def solve(stations, min_q=5.0, warn_q=10.0):
    if len(stations) < 2:
        raise GeometryError('a trajectory needs at least two cameras')
    normals = [plane_normal(st.rays) for st in stations]
    pairs = [(convergence(normals[i], normals[j]), i, j)
             for i in range(len(stations)) for j in range(i + 1, len(stations))]
    q_max, i, j = max(pairs)
    warnings = []
    if q_max < min_q and len(stations) == 2:
        raise GeometryError(f'the two planes are almost parallel (Q = {q_max:.1f} deg)')
    if q_max < warn_q:
        warnings.append(f'weak geometry: Q = {q_max:.1f} deg')

    p0, d0 = intersect_planes(stations[i], stations[j])
    e1, e2 = _perpendiculars(d0)

    def build(x):
        d = d0 + x[0] * e1 + x[1] * e2
        return p0 + 1000.0 * (x[2] * e1 + x[3] * e2), d / np.linalg.norm(d)

    # soft_l1 with a 0.3 degree scale: outlying rays (flare, a pole after the fireball faded) lose their pull
    sol = least_squares(lambda x: _ray_residuals(*build(x), stations), np.zeros(4), x_scale=[1e-3, 1e-3, 1.0, 1.0],
                        loss='soft_l1', f_scale=np.radians(0.3))
    p, d = build(sol.x)

    along = {st.name: np.array([_closest(p, d, st.origin, r)[0] for r in st.rays]) for st in stations}
    slopes = [np.polyfit(st.times, along[st.name], 1)[0] for st in stations if len(st.times) >= 2]
    if slopes and np.median(slopes) < 0:
        d = -d
        along = {k: -v for k, v in along.items()}

    all_s = np.concatenate(list(along.values()))
    begin, end = to_geodetic(p + all_s.min() * d), to_geodetic(p + all_s.max() * d)
    motion = enu_basis(end[0], end[1]) @ d
    azimuth = enu_to_azel(motion)[0]
    slope = float(np.degrees(np.arctan2(-motion[2], np.hypot(motion[0], motion[1]))))

    speeds = {}
    for st in stations:
        fit = _fit_speed(st.times, along[st.name])
        if fit:
            speeds[st.name] = (fit[0] / 1000.0, fit[1] / 1000.0)
    # A camera whose speed sits far from the others points to its clock (dropped or doubled frames), not to the
    # path: with three or more cameras it is left out of the speed, while the geometry still uses its rays.
    outliers = set()
    if len(speeds) >= 3:
        for name, (s, e) in speeds.items():
            others = np.array([o for n, (o, _) in speeds.items() if n != name])
            med = float(np.median(others))
            spread = max(float(np.std(others, ddof=1)), e, 0.05 * abs(med))
            if abs(s - med) > 3 * spread:
                outliers.add(name)
                warnings.append(f'{name}: {s:.1f} km/s is more than 3 sigma from the other cameras ({med:.1f} km/s); '
                                'left out of the speed')
    used = {k: x for k, x in speeds.items() if k not in outliers}
    v = sigma = formal = spread = None
    if used:
        vals = np.array([s for s, _ in used.values()])
        errs = np.array([max(e, 0.05) for _, e in used.values()])
        w = 1 / errs ** 2
        v, formal = float(np.sum(w * vals) / np.sum(w)), float(np.sqrt(1 / np.sum(w)))
        sigma = formal
        if len(vals) > 1:
            spread = float(np.std(vals, ddof=1) / np.sqrt(len(vals)))
            sigma = max(formal, spread)

    rms = {}
    for st in stations:
        r = _ray_residuals(p, d, [st]).reshape(-1, 3)
        rms[st.name] = float(np.degrees(np.sqrt(np.mean(np.sum(r * r, axis=1)))))

    return Solution(p, d, begin, end, azimuth, slope, enu_to_azel(-motion), v, sigma,
                    speeds, q_max, rms, warnings, tuple(sorted(outliers)), formal, spread)
