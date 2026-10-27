"""Grade an agent run against the published solution, after the fact. The agent never reads validation/.

Re-solves the run's final cameras with today's code (the same numbers the run recorded; replay checks that) and
applies the criteria fixed before the work: the four geometric ones (heading and slope within 3 deg, height at CBET's
main flare within 5 km, CBET's end point within 15 km of the line; committed on 26 October, 20:33, as the gate for
28 October) and the speed criterion planned for 29 October (within 1.5 km/s of CBET's 17.5, committed on 27 October).
validation/<event>/refereed.json, when present, adds a separate comparison with the refereed solutions that followed
CBET 3423; it was added after the first graded run and never changes the pre-registered result.
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
    cmp['gate']['speed'] = speed is not None and abs(speed - ref) <= 1.5
    grade = {'run_id': rec['run_id'], 'run_status': rec['status'], 'cameras': rec['final']['clips'], 'graded_with': 'validation/truth.json',
             'passed': f"{sum(cmp['gate'].values())} of {len(cmp['gate'])}", **cmp}
    refereed = ROOT / 'validation' / event / 'refereed.json'
    if refereed.exists():  # added after the first graded run: reported beside the pre-registered result, never in it
        slope = case.last_solution.slope
        rows = []
        for s in json.loads(refereed.read_text())['solutions']:
            row = {'who': s['who'], 'v_kms': s['v_initial_kms'],
                   'speed_within_1_5_kms': speed is not None and abs(speed - s['v_initial_kms']) <= 1.5}
            if 'slope_deg_end' in s:
                row.update(slope_end_deg=s['slope_deg_end'], slope_within_3_deg=abs(slope - s['slope_deg_end']) <= 3)
            rows.append(row)
        grade['refereed_added_after_the_run'] = rows
    (ROOT / 'validation' / event / f"grade-{rec['run_id']}.json").write_text(json.dumps(grade, indent=1) + '\n')
    print(json.dumps(grade, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:3])
