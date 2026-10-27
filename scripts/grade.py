"""Grade an agent run against the published solution, after the fact. The agent never reads validation/.

Re-solves the run's final cameras with today's code (the same numbers the run recorded; replay checks that) and
applies the four criteria of the 28-Oct gate plus the speed criterion of the 29th (17.5 +/- 1.5 km/s).
Usage: .venv/bin/python scripts/grade.py <event> [run_id]   (default: the newest run with a final solution)
Writes validation/<event>/grade-<run_id>.json.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from testigos.agent import Case  # noqa: E402
from triangulate import compare  # noqa: E402


def main(event, run_id=None):
    runs = sorted((ROOT / 'events' / event / 'runs').glob('*.json'))
    records = [json.loads(p.read_text()) for p in runs]
    rec = next((r for r in reversed(records) if (run_id is None or r['run_id'] == run_id) and r.get('final', {}) and r['final'].get('clips')), None)
    if rec is None:
        raise SystemExit(f'no run of {event} with a final trajectory' + (f' and id {run_id}' if run_id else ''))
    case = Case(event)
    case.solve(rec['final']['clips'])
    truth = json.loads((ROOT / 'validation' / event / 'truth.json').read_text())
    cmp = compare(case.last_solution, truth)
    speed, ref = cmp['speed_kms']
    cmp['gate']['speed_29_oct'] = speed is not None and abs(speed - ref) <= 1.5
    grade = {'run_id': rec['run_id'], 'run_status': rec['status'], 'cameras': rec['final']['clips'], 'graded_with': 'validation/truth.json',
             'passed': f"{sum(cmp['gate'].values())} of {len(cmp['gate'])}", **cmp}
    (ROOT / 'validation' / event / f"grade-{rec['run_id']}.json").write_text(json.dumps(grade, indent=1) + '\n')
    print(json.dumps(grade, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:3])
