"""WGS84 geodetic, Earth-centred (ECEF) and local east-north-up (ENU) frames.

Everything geometric goes through ECEF, so Earth curvature over a few hundred km is handled.
Angles are degrees, distances metres.
"""
import numpy as np

A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)


def to_ecef(lat, lon, h):
    la, lo = np.radians(lat), np.radians(lon)
    n = A / np.sqrt(1 - E2 * np.sin(la) ** 2)
    return np.array([(n + h) * np.cos(la) * np.cos(lo),
                     (n + h) * np.cos(la) * np.sin(lo),
                     (n * (1 - E2) + h) * np.sin(la)])


def to_geodetic(xyz):
    """ECEF -> (lat, lon, h); a few fixed-point steps give sub-millimetre precision."""
    x, y, z = xyz
    p = np.hypot(x, y)
    lon = np.arctan2(y, x)
    lat = np.arctan2(z, p * (1 - E2))
    for _ in range(6):
        n = A / np.sqrt(1 - E2 * np.sin(lat) ** 2)
        h = p / np.cos(lat) - n
        lat = np.arctan2(z, p * (1 - E2 * n / (n + h)))
    n = A / np.sqrt(1 - E2 * np.sin(lat) ** 2)
    return float(np.degrees(lat)), float(np.degrees(lon)), float(p / np.cos(lat) - n)


def enu_basis(lat, lon):
    """Rows are the east, north and up unit vectors expressed in ECEF."""
    la, lo = np.radians(lat), np.radians(lon)
    return np.array([[-np.sin(lo), np.cos(lo), 0.0],
                     [-np.sin(la) * np.cos(lo), -np.sin(la) * np.sin(lo), np.cos(la)],
                     [np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]])


def azel_to_enu(az, el):
    a, e = np.radians(az), np.radians(el)
    return np.array([np.cos(e) * np.sin(a), np.cos(e) * np.cos(a), np.sin(e)])


def enu_to_azel(v):
    e, n, u = v
    return float(np.degrees(np.arctan2(e, n)) % 360), float(np.degrees(np.arctan2(u, np.hypot(e, n))))


def azel_between(cam, target):
    """Azimuth (clockwise from north) and elevation of `target` seen from `cam`; both are (lat, lon, h)."""
    d = to_ecef(*target) - to_ecef(*cam)
    return enu_to_azel(enu_basis(cam[0], cam[1]) @ d)


def angle_between(u, v):
    u, v = np.asarray(u, float), np.asarray(v, float)
    c = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))
