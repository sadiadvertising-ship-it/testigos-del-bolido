import numpy as np

from synth import STATIONS, landmark
from testigos.camera import Camera, calibrate
from testigos.geo import azel_between, azel_to_enu, angle_between


def test_project_unproject_round_trip():
    cam = Camera(1920, 1080, yaw=250, pitch=12, roll=-3, hfov=70, k1=-0.05)
    for az, el in [(250, 12), (230, 5), (275, 30), (240, -2)]:
        v = azel_to_enu(az, el)
        assert angle_between(cam.unproject(cam.project(v)), v) < 1e-6


def test_behind_camera_is_not_projected():
    assert Camera(1280, 720, yaw=0, pitch=0).project(azel_to_enu(180, 0)) is None


def test_calibration_recovers_pointing_and_field_of_view():
    rng = np.random.default_rng(7)
    pos = STATIONS['chelyabinsk']
    truth = Camera(1280, 720, yaw=118.0, pitch=14.0, roll=2.0, hfov=60.0)
    lms = []
    for daz, el, km in [(-22, 1.0, 4), (-5, 2.5, 9), (14, 0.8, 6)]:
        ll = landmark(pos, truth.yaw + daz, el, km)
        lms.append((ll, truth.project_azel(*azel_between(pos, ll)) + rng.normal(0, 2.0, 2)))
    cal = calibrate(1280, 720, pos, lms, hfov_guess=65.0)
    assert abs(cal.camera.hfov - truth.hfov) < 1.0
    assert abs(cal.camera.yaw - truth.yaw) < 0.2
    assert abs(cal.camera.pitch - truth.pitch) < 0.3
    assert cal.rms_deg < 0.3 and cal.loo_deg is not None and cal.loo_deg < 0.5


def test_fisheye_round_trip_beyond_ninety_degrees():
    cam = Camera(960, 720, yaw=30, pitch=20, roll=4, hfov=185, k1=0.03, fisheye=True)
    for az, el in [(30, 20), (110, 5), (-50, 40), (30, -60)]:
        v = azel_to_enu(az, el)
        assert angle_between(cam.unproject(cam.project(v)), v) < 1e-6


def test_fisheye_calibration_from_directions():
    rng = np.random.default_rng(5)
    truth = Camera(960, 720, yaw=40.0, pitch=15.0, roll=-3.0, hfov=180.0, fisheye=True)
    dirs = [('azel', a, e) for a, e in [(-30, 2), (10, 6), (60, 1), (95, 4), (40, 45)]]
    lms = [(d, truth.project_azel(d[1], d[2]) + rng.normal(0, 1.5, 2)) for d in dirs]
    cal = calibrate(960, 720, STATIONS['south'], lms, hfov_guess=170.0, fisheye=True)
    assert abs(cal.camera.yaw - truth.yaw) < 0.5 and abs(cal.camera.hfov - truth.hfov) < 2.0
    assert cal.rms_deg < 0.5


def test_plumb_lines_recover_roll_and_barrel_distortion():
    rng = np.random.default_rng(21)
    pos = STATIONS['northeast']
    truth = Camera(1280, 720, yaw=236.0, pitch=-1.2, roll=2.5, hfov=82.0, k1=-0.09)
    lines = []
    for az in [200, 210, 222, 247, 258, 268, 274]:
        line = [truth.project_azel(az, el) for el in np.linspace(-6, 18, 5)]
        lines.append([p + rng.normal(0, 1.0, 2) for p in line if p is not None])
    vp = ('azel', 235.9, 0.0)
    tower = landmark(pos, 279.5, 12.0, 0.135)
    from testigos.camera import fit
    seed = Camera(1280, 720, yaw=239.0, pitch=-1.0, roll=0.0, hfov=80.0, k1=0.0)
    cam, report = fit(seed, pos, points=[(vp, truth.project_azel(235.9, 0.0))],
                      x_only=[(tower, truth.project_azel(*azel_between(pos, tower))[0])], plumb=lines)
    assert abs(cam.roll - truth.roll) < 0.4 and abs(cam.k1 - truth.k1) < 0.03
    assert abs(cam.yaw - truth.yaw) < 0.3 and abs(cam.hfov - truth.hfov) < 1.5
    assert report['plumb']['rms_px'] < 2.0


def test_two_landmarks_fit_exactly_and_have_no_leave_one_out():
    pos = STATIONS['south']
    truth = Camera(1280, 720, yaw=40.0, pitch=10.0, roll=0.0, hfov=55.0)
    lms = [(ll, truth.project_azel(*azel_between(pos, ll)))
           for ll in (landmark(pos, 30, 1.5, 5), landmark(pos, 52, 0.7, 8))]
    cal = calibrate(1280, 720, pos, lms)
    assert cal.rms_deg < 0.01 and cal.loo_deg is None
