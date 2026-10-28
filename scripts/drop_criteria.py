"""Tyumen's drop, measured by the agent's own code.

The case is built as the runs that solved Chelyabinsk (a996, 9c57 and cee8) had it: Kamensk-Uralskiy (2), Tyumen (48)
and Korkino (10) oriented, nothing dropped. For each criterion in agent.DROP_CRITERIA, a fresh case calls
drop_clip('48', criterion). The code measures the criterion and accepts or refuses the drop.
Then run 20261027T132419-a996 is replayed offline with agent.replay. That run dropped Tyumen without naming a
criterion. What today's code returns for its drop_clip and finalize steps is kept beside what the run recorded.
Every case is set to replaying, so no final_solution.json, report or run record is written. The script checks that no
file in events/ or out/ changed.
Writes validation/chelyabinsk-2013/drop-48-criteria.json.
Usage: .venv/bin/python scripts/drop_criteria.py
"""
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stations import ROOT  # noqa: E402
from testigos import agent  # noqa: E402

EVENT_ID, CLIP, RUN = 'chelyabinsk-2013', '48', '20261027T132419-a996'
STATE = ['2', '48', '10']  # oriented in runs a996, 9c57 and cee8, in the order of event.json
OUT = ROOT / 'validation' / EVENT_ID / 'drop-48-criteria.json'


def snapshot():
    """sha1 of every file under events/ and out/."""
    return {str(p.relative_to(ROOT)): hashlib.sha1(p.read_bytes()).hexdigest()
            for d in ('events', 'out') for p in sorted((ROOT / d).rglob('*')) if p.is_file()}


def fresh_case():
    case = agent.Case(EVENT_ID)
    case.replaying = True  # the tools write nothing while replaying
    if case.oriented() != STATE or case.dropped:
        raise SystemExit(f'the case is not in the runs\' state: oriented {case.oriented()}, dropped {case.dropped}')
    return case


def criteria():
    out = {}
    for criterion in agent.DROP_CRITERIA:
        r = fresh_case().drop_clip(CLIP, criterion=criterion)
        out[criterion] = {'accepted': r['accepted'], 'measured': r['measured']}
        if r.get('problems'):
            out[criterion]['problems'] = r['problems']
    pairs = out['raises_residuals']['measured'].get('residual_rms_deg_with_and_without', {})
    out['raises_residuals']['rise_with_it'] = {c: {'deg': round(w - wo, 3), 'percent': round(100 * (w - wo) / wo, 1)}
                                               for c, (w, wo) in pairs.items()}
    return out


def replay_first_run():
    record = json.loads((ROOT / 'events' / EVENT_ID / 'runs' / f'{RUN}.json').read_text())
    recorded = {s['step']: s for s in record['steps']}
    steps = []
    result = agent.replay(EVENT_ID, RUN, echo=steps.append)
    out = {'run_id': RUN, 'steps': result['steps'],
           'steps_that_differ_today': [f"{d['step']} {d['action']}" for d in result['differences']]}
    for s in steps:
        if s['action'] in ('drop_clip', 'finalize'):
            then = recorded[s['step']]
            was = then['result']
            if s['action'] == 'finalize' and was.get('final'):
                was = {'accepted': was['accepted'], 'final_clips': was['final']['clips']}
            out[s['action']] = {'step': s['step'], 'args': {k: v for k, v in (then.get('args') or {}).items() if k != 'why'},
                                'recorded': was, 'today': s['result']}
    return out


def sentences(out, site):
    """The findings in plain sentences, every figure taken from the results above."""
    c, me = out['criteria'], site[CLIP]
    accepted = [k for k, r in c.items() if r['accepted']]
    s = [f"Of the {len(c)} drop criteria, the code accepts {' and '.join(accepted) or 'none'} for {me}."]
    for k, pair in c['near_parallel_pair']['measured'].get('near_parallel_with', {}).items():
        rest = ' and '.join(site[o] for o in out['oriented'] if o not in (CLIP, k))
        s.append(f"near_parallel_pair {'holds' if c['near_parallel_pair']['accepted'] else 'does not hold'}: {me}'s planes "
                 f"cross {site[k]}'s at {pair['q_deg_with_it']} degrees. {site[k]}'s planes cross {rest}'s at "
                 f"{pair['its_widest_q_deg']} degrees, and {me}'s cross {rest}'s at {pair['this_widest_q_deg']}.")
    m = c['narrow_planes']['measured']
    s.append(f"narrow_planes {'holds' if c['narrow_planes']['accepted'] else 'does not hold'}: {me}'s planes cross "
             + ' and '.join(f"{site[k]}'s at {q} degrees" for k, q in m.get('q_deg_with_kept', {}).items())
             + f", and the criterion asks under {m.get('threshold_deg')} degrees with every kept camera.")
    r = c['raises_residuals']
    parts = [f"{site[k]}'s residual goes from {wo} to {w} degrees ({r['rise_with_it'][k]['percent']} percent)"
             for k, (w, wo) in r['measured'].get('residual_rms_deg_with_and_without', {}).items()]
    s.append(f"raises_residuals {'holds' if r['accepted'] else 'does not hold'}: with {me}, " + ' and '.join(parts)
             + f". The code's threshold is \"{r['measured'].get('threshold')}\".")
    s.append(f"not_oriented {'holds' if c['not_oriented']['accepted'] else 'does not hold'}: "
             f"{c['not_oriented']['measured'].get('note')}.")
    d, f = out['replay']['drop_clip'], out['replay']['finalize']
    s.append(f"Run {RUN} dropped {me} without naming a criterion. Replayed with today's code, its drop_clip "
             f"(step {d['step']}) returns \"{d['today'].get('error', d['today'])}\", and its finalize (step {f['step']}) is "
             + ('accepted.' if f['today'].get('accepted') else 'refused: ' + '; '.join(f['today'].get('problems', [])) + '.'))
    return s


def main():
    before = snapshot()
    state = fresh_case()
    site = {c: state._clip_entry(c)['site'] for c in state.clip_ids()}
    out = {'note': __doc__.split('Writes')[0].strip(), 'clip': CLIP, 'oriented': state.oriented(), 'dropped': state.dropped,
           'planes': state.planes()['pairs'], 'criteria': criteria(), 'replay': replay_first_run()}
    changed = [k for k, v in snapshot().items() if before.get(k) != v] + [k for k in before if k not in snapshot()]
    if changed:
        raise SystemExit(f'files changed under events/ or out/: {changed}')
    out['files_changed_under_events_and_out'] = changed
    out['summary'] = sentences(out, site)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print('\n'.join(out['summary']))


if __name__ == '__main__':
    main()
