"""The agent loop with a scripted planner: tools run, failures become facts, the log keeps the reasons."""
import json

from testigos import agent


def test_scripted_case_runs_tools_and_logs_reasons(tmp_path, monkeypatch):
    ev = tmp_path / 'events' / 'demo'
    ev.mkdir(parents=True)
    (ev / 'event.json').write_text(json.dumps({'id': 'demo', 'utc': '2013-02-15T03:20:20Z', 'clips': [{'catalog_no': 1}, {'catalog_no': 2}]}))
    monkeypatch.setattr(agent, 'ROOT', tmp_path)
    script = iter([
        {'why': 'see what is calibrated', 'action': 'calibration', 'clip': '1', 'clips': None, 'reason': None},
        {'why': 'cannot solve with one camera', 'action': 'solve', 'clip': None, 'clips': ['1', '2'], 'reason': None},
        {'why': 'clip 2 has no landmarks', 'action': 'drop_clip', 'clip': '2', 'clips': None, 'reason': 'no surveyed landmark'},
        {'why': 'nothing more to do', 'action': 'done', 'clip': None, 'clips': None, 'reason': None},
    ])
    case = agent.Case('demo')
    log = case.run(planner=lambda state, i, n: next(script), max_steps=6)
    assert [s['action'] for s in log] == ['calibration', 'solve', 'drop_clip', 'done']
    assert log[0]['result'] == {'calibrated': False, 'why': 'no surveyed landmark or line set confirmed for this camera'}
    assert 'error' in log[1]['result']  # a failed tool is reported back, not raised
    assert case.dropped == {'2': 'no surveyed landmark'}
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
    r = case.solve(clips=list(STATIONS))
    assert r['verdict'] == 'reentry', r['verdict_reason']
    assert r['seen_for_s'] > 20


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
