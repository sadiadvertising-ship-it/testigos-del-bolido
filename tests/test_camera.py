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


def test_two_landmarks_fit_exactly_and_have_no_leave_one_out():
    pos = STATIONS['south']
    truth = Camera(1280, 720, yaw=40.0, pitch=10.0, roll=0.0, hfov=55.0)
    lms = [(ll, truth.project_azel(*azel_between(pos, ll)))
           for ll in (landmark(pos, 30, 1.5, 5), landmark(pos, 52, 0.7, 8))]
    cal = calibrate(1280, 720, pos, lms)
    assert cal.rms_deg < 0.01 and cal.loo_deg is None
