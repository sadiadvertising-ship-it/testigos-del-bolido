"""Command line for the case agent.

  python -m testigos run <event>                   the agent works the case (Muse Spark 1.3 tool calling); one line per step
  python -m testigos resume <event> <run_id>       continue a blocked run once its inputs changed, or with --notes
  python -m testigos review <event> <run_id> --approve | --reject [--notes ...] [--by NAME]
  python -m testigos replay <event> <run_id>       re-run the recorded tool calls with today's code, offline
"""
import argparse
import json
import sys

from . import agent


def short(r):
    if not isinstance(r, dict):
        return str(r)[:90]
    if 'error' in r:
        return 'error: ' + str(r['error'])[:80]
    if 'pairs' in r:
        return 'Q ' + ', '.join(f"{a}-{b} {p['q_deg']}°" for p in r['pairs'] for a, b in [p['pair']])[:90]
    if 'reports' in r:
        return ', '.join(f"{lang} {v['traced']}/{v['figures']} figures traced" for lang, v in r['reports'].items()
                         if isinstance(v, dict)) + f" -> {r['status']}"
    if 'accepted' in r:
        if r['accepted']:
            return 'blocked: waiting for evidence' if r.get('blocked') else (
                'accepted: insufficient geometry' if r.get('insufficient_geometry') else 'accepted')
        return 'REFUSED: ' + '; '.join(r.get('problems', []))[:120]
    if 'azimuth_deg' in r:
        return f"{r['azimuth_deg']}° heading, {r['slope_deg']}° slope, {r['speed_kms']} km/s, Q {r['q_max_deg']}°, {r['verdict']}"
    if 'detections' in r:
        return f"{len(r['detections'])} satellite detections"
    if 'best_towns' in r:
        return 'towns: ' + ', '.join(t.split(' (')[0] for t in r['best_towns'][:4])
    if 'dropped' in r:
        return f"dropped {r['dropped']}"
    if 'calibrated' in r:
        return 'oriented' if r['calibrated'] else 'not oriented'
    if 'clip_kind' in r:
        return f"{r['clip_kind']}, {len(r.get('landmarks', []))} landmark guesses"
    return json.dumps(r, ensure_ascii=False, default=str)[:90]


def echo(step):
    target = '+'.join(step['clips']) if step.get('clips') else (step.get('clip') or '')
    print(f"{step['step']:02d}  {step['action']:<16} {target:<10} | {str(step.get('why', ''))[:90]}\n    -> {short(step['result'])}",
          flush=True)


def _ended(case):
    print(f"run {case.run_id}: {case.status}" + (f" ({case.block['reason']})" if case.block else ''))


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m testigos')
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('event')
    r.add_argument('--max-steps', type=int, default=16)
    r.add_argument('--json-planner', action='store_true', help='the single-turn JSON planner (Muse Spark 1.2) instead of tool calling')
    s = sub.add_parser('resume')
    s.add_argument('event')
    s.add_argument('run_id')
    s.add_argument('--notes')
    v = sub.add_parser('review')
    v.add_argument('event')
    v.add_argument('run_id')
    choice = v.add_mutually_exclusive_group(required=True)
    choice.add_argument('--approve', action='store_true')
    choice.add_argument('--reject', action='store_true')
    v.add_argument('--notes')
    v.add_argument('--by')
    y = sub.add_parser('replay')
    y.add_argument('event')
    y.add_argument('run_id')
    a = p.parse_args(argv)

    if a.cmd == 'run':
        case = agent.Case(a.event)
        case.echo = echo
        case.run(planner=agent.muse_planner if a.json_planner else None, max_steps=a.max_steps)
        _ended(case)
    elif a.cmd == 'resume':
        changed = agent.changed_inputs(a.event, a.run_id)
        if not changed and not a.notes:
            print(f'nothing changed since run {a.run_id} and no reviewer notes: the run stays blocked, no model call')
            return 1
        print('changed since the run: ' + (', '.join(changed) if changed else 'none (reviewer notes)'))
        case = agent.Case(a.event)
        case.echo = echo
        case.run(notes=a.notes, resumed_from=a.run_id)
        _ended(case)
    elif a.cmd == 'review':
        rec = agent.review(a.event, a.run_id, approve=a.approve, notes=a.notes, by=a.by)
        print(f"run {a.run_id}: {rec['status']}")
    elif a.cmd == 'replay':
        out = agent.replay(a.event, a.run_id)
        print(f"replayed {out['steps']} steps of {a.run_id}: "
              + ('no differences' if not out['differences'] else f"{len(out['differences'])} differences"))
        for d in out['differences']:
            print(json.dumps(d, ensure_ascii=False, default=str)[:600])
        return 1 if out['differences'] else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
