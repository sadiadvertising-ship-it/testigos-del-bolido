import numpy as np

from testigos.geo import azel_between, azel_to_enu, enu_to_azel, to_ecef, to_geodetic


def test_ecef_round_trip():
    for p in [(3.45, -76.53, 1000.0), (54.92, 60.61, 14940.0), (-33.9, 151.2, -10.0)]:
        lat, lon, h = to_geodetic(to_ecef(*p))
        assert abs(lat - p[0]) < 1e-9 and abs(lon - p[1]) < 1e-9 and abs(h - p[2]) < 1e-3


def test_azel_round_trip():
    for az, el in [(0, 0), (90, 10), (279.5, -16.5), (359.9, 80)]:
        a, e = enu_to_azel(azel_to_enu(az, el))
        assert abs((a - az + 180) % 360 - 180) < 1e-9 and abs(e - el) < 1e-9


def test_azel_between_east_and_up():
    cam = (3.45, -76.53, 1000.0)
    az, el = azel_between(cam, (cam[0], cam[1] + 0.0899, cam[2] + 1000))  # about 10 km east, 1 km up
    assert abs(az - 90) < 0.1
    assert abs(el - np.degrees(np.arctan2(1000, 10000))) < 0.1
