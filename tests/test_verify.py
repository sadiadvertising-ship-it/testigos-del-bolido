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
    assert r['numbers'] >= 5


def test_an_invented_figure_and_a_swapped_hemisphere_are_caught():
    text, facts = _case('chelyabinsk-2013')  # whatever the current wording, an added false sentence must be caught
    r = check_report(text + '\nRumbo 987,6 grados; final en 54,914 S.', facts)
    assert not r['passed'] and '987,6' in r['orphans']
    assert any(m.startswith('54,914 S') for m in r['hemisphere_mismatches'])


def test_a_changed_satellite_position_is_caught():
    text, facts = _case('colombia-2025-07-30')
    r = check_report(text + ' El satélite lo ubicó en 6,64 N.', facts)
    assert not r['passed'] and '6,64' in r['orphans']


def test_list_numbers_and_sigma_names_are_not_figures():
    r = check_report('Pasos:\n1. revisar\n2. medir dentro de 2σ y 1 sigma', [])
    assert r['passed'] and r['numbers'] == 0


def test_a_time_inside_an_iso_timestamp_is_traceable():
    assert check_report('El destello fue a las 03:50 UTC.', [{'utc': '2025-07-31T03:50:24Z'}])['passed']
