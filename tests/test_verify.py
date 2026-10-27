"""The report check: every figure and hemisphere must come from the run's tool results."""
import json
import pathlib

import pytest

from testigos.verify import check_report

EVENTS = pathlib.Path(__file__).resolve().parents[1] / 'events'


def _case(event):
    d = EVENTS / event
    log = json.loads((d / 'agent_log.json').read_text())
    facts = [s['result'] for s in log] + [json.loads((d / 'event.json').read_text())]
    return (d / 'agent_report_es.md').read_text(), facts


@pytest.mark.parametrize('event', ['chelyabinsk-2013', 'colombia-2025-07-30'])
def test_committed_reports_trace_every_figure(event):
    text, facts = _case(event)
    r = check_report(text, facts)
    assert r['passed'], r
    assert r['numbers'] > 10


def test_an_invented_figure_and_a_swapped_hemisphere_are_caught():
    text, facts = _case('chelyabinsk-2013')
    r = check_report(text.replace('282,12', '283,12', 1).replace('64,101 E', '64,101 W', 1), facts)
    assert not r['passed']
    assert r['orphans'] == ['283,12']
    assert r['hemisphere_mismatches'] and r['hemisphere_mismatches'][0].startswith('64,101 W')


def test_a_changed_satellite_position_is_caught():
    text, facts = _case('colombia-2025-07-30')
    assert '6.46' in text
    r = check_report(text.replace('6.46', '6.64'), facts)
    assert not r['passed'] and any(o.startswith('6.64') for o in r['orphans'])


def test_list_numbers_and_sigma_names_are_not_figures():
    r = check_report('Pasos:\n1. revisar\n2. medir dentro de 2σ y 1 sigma', [])
    assert r['passed'] and r['numbers'] == 0
