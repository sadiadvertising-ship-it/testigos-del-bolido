import numpy as np
import pytest

from synth import BEGIN, END, STATIONS, distance_to_line, exact_station, filmed_station, path, true_motion_enu, true_speed_kms
from testigos.geo import enu_basis, enu_to_azel, to_ecef
from testigos.solve import GeometryError, Station, solve


def _truth_angles():
    m = true_motion_enu()
    return enu_to_azel(m)[0], float(np.degrees(np.arctan2(-m[2], np.hypot(m[0], m[1]))))


def test_three_cameras_noise_free():
    t, pts = path()
    sol = solve([exact_station(n, t, pts) for n in STATIONS])
    az, slope = _truth_angles()
    assert distance_to_line(sol, BEGIN) < 50 and distance_to_line(sol, END) < 50
    end_error = np.linalg.norm(to_ecef(*sol.end) - to_ecef(*END))
    assert end_error < 1000
    assert abs(sol.speed_kms - true_speed_kms()) < 0.3
    assert abs(sol.azimuth - az) < 0.5 and abs(sol.slope - slope) < 0.5
    assert not sol.warnings


def test_noise_keeps_the_path_within_a_kilometre():
    rng = np.random.default_rng(3)
    t, pts = path()
    sol = solve([exact_station(n, t, pts, noise_deg=0.05, rng=rng) for n in STATIONS])
    assert distance_to_line(sol, END) < 1500
    assert abs(sol.speed_kms - true_speed_kms()) < 0.6


def test_end_to_end_from_landmark_calibration():
    rng = np.random.default_rng(11)
    t, pts = path()
    views = [('chelyabinsk', 150, 18, 1.5, 90), ('south', 75, 20, -2.0, 90), ('northeast', 200, 15, 0.5, 90)]
    stations = []
    for name, yaw, pitch, roll, hfov in views:
        st, cal = filmed_station(name, yaw, pitch, roll, hfov, t, pts, rng)
        assert cal.rms_deg < 0.3
        assert len(st.times) >= 10, name
        stations.append(st)
    sol = solve(stations)
    az, slope = _truth_angles()
    assert distance_to_line(sol, END) < 3000 and distance_to_line(sol, BEGIN) < 3000
    assert abs(sol.speed_kms - true_speed_kms()) < 0.6
    assert abs(sol.azimuth - az) < 1.5 and abs(sol.slope - slope) < 1.5


def test_flare_outliers_do_not_tilt_the_path():
    rng = np.random.default_rng(9)
    t, pts = path()
    stations = []
    for n in STATIONS:
        st = exact_station(n, t, pts, noise_deg=0.02, rng=rng)
        rays = st.rays_enu.copy()
        bad = slice(len(rays) // 2, len(rays) // 2 + max(len(rays) // 8, 3))  # a burst of glow-centre points off the head
        rays[bad] = rays[bad] + np.array([0.0, 0.0, 0.03])
        rays /= np.linalg.norm(rays, axis=1)[:, None]
        stations.append(Station(n, st.pos, st.times, rays))
    sol = solve(stations)
    assert distance_to_line(sol, END) < 1500 and distance_to_line(sol, BEGIN) < 1500


def test_direction_follows_the_clock_not_the_ray_order():
    t, pts = path()
    stations = []
    for n in STATIONS:
        st = exact_station(n, t, pts)
        stations.append(Station(n, st.pos, st.times[::-1].copy(), st.rays_enu[::-1].copy()))
    sol = solve(stations)
    assert sol.speed_kms > 0
    assert sol.end[2] < sol.begin[2]


def test_two_cameras_under_the_ground_track_are_refused():
    t, pts = path()
    under = {'a': (54.6115, 63.351, 200.0), 'b': (54.839, 61.338, 200.0)}
    stations = []
    for name, pos in under.items():
        v = (pts - to_ecef(*pos)) @ enu_basis(pos[0], pos[1]).T
        v /= np.linalg.norm(v, axis=1)[:, None]
        keep = v[:, 2] > 0.05
        stations.append(Station(name, pos, t[keep], v[keep]))
    with pytest.raises(GeometryError):
        solve(stations)


def test_a_camera_with_a_wrong_clock_is_left_out_of_the_speed():
    t, pts = path()
    stations = [exact_station(n, t, pts) for n in STATIONS]
    slow = stations[0]
    stations[0] = Station(slow.name, slow.pos, slow.times * 1.3, slow.rays_enu)  # its clock runs 30 % slow
    sol = solve(stations)
    assert any(slow.name in w and 'left out of the speed' in w for w in sol.warnings)
    assert abs(sol.speed_kms - true_speed_kms()) < 0.3
