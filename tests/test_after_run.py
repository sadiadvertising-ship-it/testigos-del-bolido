"""The cameras oriented after the signed run (validation/chelyabinsk-2013/after-run/): the agent never sees them, so the
signed run replays unchanged; Yekaterinburg's stored camera is what its committed evidence fits to; the held-out numbers
are current; and only the camera judged oriented reaches the viewer. No network."""
import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
_spec = importlib.util.spec_from_file_location('holdout', ROOT / 'scripts' / 'holdout.py')
holdout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(holdout)
import export_web as ex  # noqa: E402
import stations  # noqa: E402
from testigos import agent  # noqa: E402
from testigos.camera import Camera  # noqa: E402

CASE = 'chelyabinsk-2013'
VAL = ROOT / 'validation' / CASE
CAMS = json.loads((VAL / 'after-run' / 'cameras.json').read_text())
AIMED = json.loads((VAL / 'after-run' / 'aimed-with-path.json').read_text())


def test_the_agent_never_sees_them_and_the_signed_run_replays_unchanged():
    case = agent.Case(CASE)
    assert not any(case.calibration(k)['calibrated'] for k in ('81', '238', '15', '257', '14'))
    assert not [k for k in case._inputs() if k.startswith('validation')]
    assert agent.replay(CASE, CAMS['signed_run'])['differences'] == []


def test_yekaterinburgs_camera_is_the_fit_of_its_committed_evidence():
    e = CAMS['chelyabinsk-2013-81']
    stored = Camera(*e['image'], fisheye=True, **e['camera'])
    cam, pos, report = stations.yekaterinburg_camera(seed=stored, iters=1, with_report=True)
    for k, v in e['camera'].items():
        assert getattr(cam, k) == pytest.approx(v, abs=2e-3), k
    assert pos == tuple(e['camera_pos'])
    assert {k: round(v['rms_deg'], 3) for k, v in report.items() if v['n']} == e['fit_rms_deg']


def test_the_held_out_numbers_are_current():
    case = agent.Case(CASE)
    fits = case._stations(['2', '10'])
    sol = holdout.solve(fits)
    committed = json.loads((VAL / 'holdout-after-run.json').read_text())
    assert committed['fit_cameras'] == ['2', '10'] and committed['fit_speed_kms'] == round(sol.speed_kms, 2)
    assert set(committed['cameras']) == {'81', '238', '15', '257'}
    for clip, row in committed['cameras'].items():
        st = ex.station(case, clip)
        assert {**holdout.held(sol, st), 'plane_rms_deg': round(ex.miss_deg(sol, st), 3)} == \
            {k: row[k] for k in ('rays', 'miss_deg', 'own_clock_speed_kms', 'own_clock_speed_sigma_kms', 'plane_rms_deg')}
    yek = committed['cameras']['81']
    assert yek['outcome'] == 'oriented' and yek['plane_rms_deg'] < 0.43  # Tyumen's, a camera curated with CBET in view
    assert abs(yek['own_clock_speed_kms'] - committed['fit_speed_kms']) < 0.5
    for clip in ('238', '15', '257'):  # a rough orientation shows in the camera's own clock along the path
        assert committed['cameras'][clip]['outcome'] == 'rough'
        assert abs(committed['cameras'][clip]['own_clock_speed_kms'] - committed['fit_speed_kms']) > 8


def test_only_the_camera_judged_oriented_reaches_the_viewer():
    data = json.loads((ROOT / 'web' / 'data' / f'{CASE}.json').read_text())
    drawn = {s['id']: s for s in data['stations'] if s.get('rays')}
    assert set(drawn) == {'2', '10', '48', '81'}
    yek = drawn['81']
    assert yek['status'] == 'after run' and yek['after_run']['from'] == CAMS['chelyabinsk-2013-81']['summary']
    assert yek['miss_deg'] == json.loads((VAL / 'holdout-after-run.json').read_text())['cameras']['81']['plane_rms_deg']
    assert data['solution']['clips'] == ['2', '10']  # the fit is the signed run's
    assert {s['id'] for s in data['stations'] if s['status'] == 'not calibrated'} == {'14', '15', '257', '238'}


def test_no_frame_and_no_witness_location_beyond_the_catalogue():
    for f in (VAL / 'after-run').iterdir():
        assert f.suffix == '.json', f.name
        text = f.read_text()
        assert '/Users/' not in text and '/private/' not in text and 'scratchpad' not in text
    for k, e in {**CAMS, **AIMED}.items():
        if isinstance(e, dict) and 'camera_pos' in e:  # the Ondřejov catalogue's position, as published
            ev = next(c for c in agent.Case(CASE).event['clips'] if f"{CASE}-{c['catalog_no']}" == k)
            assert np.allclose(e['camera_pos'][:2], [ev['lat'], ev['lon']], atol=1e-6), k


def test_the_estimated_directions_are_drawn_apart_and_used_in_nothing():
    """Plast, Chebarkul and Magnitogorsk (rough, oriented without the path) and Beloretsk (aimed with the path) reach the
    viewer only as dotted lines of sight: no rays, no speed, not in the fit, and the aimed one is held out of nothing."""
    data = json.loads((ROOT / 'web' / 'data' / f'{CASE}.json').read_text())
    guessed = {s['id']: s for s in data['stations'] if s.get('guess')}
    assert {k: s['guess']['kind'] for k, s in guessed.items()} == {'238': 'rough', '15': 'rough', '257': 'rough', '14': 'aimed'}
    assert all(s['status'] == 'not calibrated' and 'rays' not in s and 'speed_kms' not in s for s in guessed.values())
    held = json.loads((VAL / 'holdout-after-run.json').read_text())['cameras']
    for k in ('238', '15', '257'):
        assert guessed[k]['guess']['miss_deg'] == round(held[k]['plane_rms_deg'], 2)
    assert '14' not in held
    aimed = AIMED['chelyabinsk-2013-14']
    assert aimed['outcome'] == 'aimed' and aimed['fit_rms_px'] < 10 and 'checks nothing' in aimed['how']
    shown = {v['clip']: v['estimate'] for v in data['videos']['shown']}
    assert shown == {'48': None, '10': None, '81': None, '14': 'aimed', '15': 'rough', '257': 'rough', '238': 'rough'}
