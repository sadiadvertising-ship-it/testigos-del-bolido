"""The agent loop with a scripted planner: tools run, failures become facts, the log keeps the reasons."""
import json

import pytest

from testigos import agent, verdict


def test_scripted_case_runs_tools_and_logs_reasons(tmp_path, monkeypatch):
    ev = tmp_path / 'events' / 'demo'
    ev.mkdir(parents=True)
    (ev / 'event.json').write_text(json.dumps({'id': 'demo', 'utc': '2013-02-15T03:20:20Z', 'clips': [{'catalog_no': 1}, {'catalog_no': 2}]}))
    monkeypatch.setattr(agent, 'ROOT', tmp_path)
    script = iter([
        {'why': 'see what is calibrated', 'action': 'calibration', 'clip': '1', 'clips': None, 'reason': None},
        {'why': 'cannot solve with one camera', 'action': 'solve', 'clip': None, 'clips': ['1', '2'], 'reason': None},
        {'why': 'clip 2 has no landmarks', 'action': 'drop_clip', 'clip': '2', 'clips': None, 'reason': 'no surveyed landmark',
         'criterion': 'not_oriented'},
        {'why': 'nothing more to do', 'action': 'done', 'clip': None, 'clips': None, 'reason': None},
    ])
    case = agent.Case('demo')
    log = case.run(planner=lambda state, i, n: next(script), max_steps=6)
    assert [s['action'] for s in log] == ['calibration', 'solve', 'drop_clip', 'done']
    assert log[0]['result'] == {'calibrated': False, 'why': 'no surveyed landmark or line set confirmed for this camera'}
    assert 'error' in log[1]['result']  # a failed tool is reported back, not raised
    assert case.dropped == {'2': {'criterion': 'not_oriented', 'reason': 'no surveyed landmark'}}
    assert json.loads((ev / 'agent_log.json').read_text())[2]['why'] == 'clip 2 has no landmarks'


def test_solve_hands_slope_and_duration_to_the_verdict(tmp_path, monkeypatch):
    """A slow, long passage reads as a re-entry; without slope and duration the agent could only say inconclusive."""
    import numpy as np
    from synth import BEGIN, END, STATIONS, exact_station
    from testigos.geo import to_ecef

    ev = tmp_path / 'events' / 'slow'
    ev.mkdir(parents=True)
    (ev / 'event.json').write_text(json.dumps({'id': 'slow', 'utc': '2025-07-31T03:50:24Z', 'clips': [{'id': n} for n in STATIONS]}))
    monkeypatch.setattr(agent, 'ROOT', tmp_path)
    t = np.linspace(0.0, 40.0, 160)
    b, e = to_ecef(*BEGIN), to_ecef(*END)
    pts = b + (e - b) * (t / t[-1])[:, None]  # about 6 km/s for 40 s, like a decaying satellite
    case = agent.Case('slow')
    monkeypatch.setattr(case, '_stations', lambda clips: [exact_station(n, t, pts) for n in clips])
    handed, decide = {}, verdict.decide
    monkeypatch.setattr(verdict, 'decide', lambda *a, **k: handed.update(k) or decide(*a, **k))
    r = case.solve(clips=list(STATIONS))
    assert r['verdict'] == 'reentry', r['verdict_reason']
    assert r['seen_for_s'] > 20
    assert handed['slope_deg'] == pytest.approx(r['slope_deg'], abs=0.01)
    assert handed['duration_s'] == pytest.approx(r['seen_for_s'], abs=0.1)


def test_a_distrusted_clock_does_not_stretch_the_passage(tmp_path, monkeypatch):
    """solve() keeps a camera with a doubled clock out of the speed; its span must not make a short passage look long."""
    import numpy as np
    from synth import BEGIN, END, STATIONS, exact_station
    from testigos.geo import to_ecef
    from testigos.solve import Station

    ev = tmp_path / 'events' / 'stretched'
    ev.mkdir(parents=True)
    (ev / 'event.json').write_text(json.dumps({'id': 'stretched', 'utc': '2025-07-31T03:50:24Z', 'clips': []}))
    monkeypatch.setattr(agent, 'ROOT', tmp_path)
    t = np.linspace(0.0, 12.0, 60)
    b, e = to_ecef(*BEGIN), to_ecef(*END)
    start = b + (e - b) * (2 / 3)
    pts = start + (e - start) * (t / t[-1])[:, None]  # the last third of the path, about 7 km/s for 12 s

    def stations(clips):
        out = [exact_station(n, t, pts) for n in clips]
        slowed = out[0]  # a slow-motion upload: every timestamp doubled
        out[0] = Station(slowed.name, slowed.pos, slowed.times * 2, slowed.rays_enu)
        return out

    case = agent.Case('stretched')
    monkeypatch.setattr(case, '_stations', stations)
    r = case.solve(clips=list(STATIONS))
    assert any('left out of the speed' in w for w in r['warnings'])
    assert r['seen_for_s'] < 13
    assert r['verdict'] == 'inconclusive', r['verdict_reason']


def test_check_satellite_reads_the_committed_window(tmp_path, monkeypatch):
    import datetime as dt
    ev = tmp_path / 'events' / 'glm'
    ev.mkdir(parents=True)
    (ev / 'event.json').write_text(json.dumps({'id': 'glm', 'utc': '2025-07-31T03:50:24Z', 'clips': []}))
    flash = dt.datetime(2025, 7, 31, 3, 50, 23, 700000, tzinfo=dt.timezone.utc)
    hit = {'datetime': flash.timestamp() * 1000, 'latitude': 6.46, 'longitude': -72.212, 'humanClassification': 'Bolide',
           'brightness': {}, 'duration': 1.05}
    (ev / 'glm-window.json').write_text(json.dumps({'events': [hit]}))
    monkeypatch.setattr(agent, 'ROOT', tmp_path)  # no out/cache catalog under tmp_path: only the window can answer
    r = agent.Case('glm').check_satellite()
    assert r['detections'][0]['utc'] == '2025-07-31T03:50:23Z'
    assert r['detections'][0]['where'] == '6.460 N, 72.212 W'
