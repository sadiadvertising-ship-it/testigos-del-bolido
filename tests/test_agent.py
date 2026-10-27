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
