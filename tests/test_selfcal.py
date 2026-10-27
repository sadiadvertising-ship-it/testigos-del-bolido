"""A third camera whose field of view is unknown can be calibrated by the trajectory itself.

Two calibrated stations fix a line; the third camera's lines of sight must meet that same line, and only
one field of view makes them do so. This is ordinary self-calibration in bundle adjustment, and it never
uses a published trajectory.
"""
import numpy as np
from scipy.optimize import minimize_scalar

from synth import STATIONS, exact_station, path, rays_from
from testigos.camera import Camera, fit
from testigos.solve import Station, solve

STREET = (75.0, 0.0)  # bearing of a street the third camera looks along


def _street_edges(cam, offsets=((-6, 3), (6, 3), (-6, 0), (6, 0))):
    """Pixels along kerbs and roof lines parallel to the street, at lateral/vertical offsets in metres."""
    az = np.radians(STREET[0])
    fwd, right = np.array([np.sin(az), np.cos(az), 0.0]), np.array([np.cos(az), -np.sin(az), 0.0])
    lines = []
    for lat_off, h in offsets:
        pts = []
        for dist in np.linspace(15, 120, 6):
            v = fwd * dist + right * lat_off + np.array([0, 0, h - 1.3])
            p = cam.project(v / np.linalg.norm(v))
            if p is not None and 0 <= p[0] < cam.width and 0 <= p[1] < cam.height:
                pts.append(p)
        if len(pts) >= 3:
            lines.append((STREET, pts))
    return lines


def _poles(cam, spots=((-6, 25), (7, 40), (-6, 60), (7, 90))):
    """Pixels along vertical poles beside the street. Edges parallel to one direction cannot fix the
    rotation about that direction; verticals can."""
    az = np.radians(STREET[0])
    fwd, right = np.array([np.sin(az), np.cos(az), 0.0]), np.array([np.cos(az), -np.sin(az), 0.0])
    lines = []
    for lat_off, dist in spots:
        pts = []
        for h in np.linspace(0.0, 8.0, 5):
            v = fwd * dist + right * lat_off + np.array([0, 0, h - 1.3])
            p = cam.project(v / np.linalg.norm(v))
            if p is not None and 0 <= p[0] < cam.width and 0 <= p[1] < cam.height:
                pts.append(p)
        if len(pts) >= 3:
            lines.append(pts)
    return lines


def test_third_camera_field_of_view_from_the_trajectory():
    t, pts = path()
    a, b = exact_station('chelyabinsk', t, pts), exact_station('northeast', t, pts)
    pos = STATIONS['south']
    truth = Camera(1280, 720, yaw=78.0, pitch=14.0, roll=1.5, hfov=96.0, k1=-0.05)
    keep, v = rays_from(pos, pts)
    pix = [(ti, truth.project(vi)) for ti, vi, k in zip(t, v, keep) if k]
    pix = [(ti, p) for ti, p in pix if p is not None and 0 <= p[0] < 1280 and 0 <= p[1] < 720]
    edges, poles = _street_edges(truth), _poles(truth)

    def residual(hfov):
        seed = Camera(1280, 720, yaw=76.0, pitch=12.0, roll=0.0, hfov=hfov, k1=0.0)
        cam, _ = fit(seed, pos, parallel=edges, plumb=poles, free=('yaw', 'pitch', 'roll', 'k1'))
        c = Station('c', pos, np.array([ti for ti, _ in pix]), np.array([cam.unproject(p) for _, p in pix]))
        sol = solve([a, b, c])
        return float(np.mean([r ** 2 for r in sol.residual_rms_deg.values()]))

    best = minimize_scalar(residual, bounds=(70, 130), method='bounded', options={'xatol': 0.1})
    assert abs(best.x - truth.hfov) < 2.0
