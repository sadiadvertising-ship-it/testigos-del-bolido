"""Every number in a report has to come from a tool result of the same run.

Muse Spark writes the report from the tool results; this check sits inside write_report, so the model cannot skip it
(the pattern of Meta's agent workshop: checks outside the model, at the points that matter). It takes each number in
the text (decimal comma or point, ranges, clip pairs, dates, scientific notation) and each hemisphere letter next to a
coordinate, and matches them against the tool results within the precision the text prints. It catches invented or
mistyped figures and swapped hemispheres; it does not judge qualitative claims.
"""
from __future__ import annotations

import json
import re

NUMBER = re.compile(r'(?<![\w.])\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?')
IN_RESULTS = re.compile(r'\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?')  # also digits after a letter, such as the hour in '...T03:50:24Z'
COORD = re.compile(r'(\d+(?:[.,]\d+)?)\s*°?\s*([NSEWO])\b')
LIST_MARKER = re.compile(r'^\s*(\d+)[.)]\s', re.M)  # '1. ' starting a line numbers a list, it is not a figure
SIGMA = re.compile(r'(?<![\w.])([123])\s*(?:σ|sigma)')  # the 1 in '1σ' names a range, it is not a figure


def _readings(token):
    """A token's value and printed decimals; with a comma, both the decimal-comma and the thousands reading."""
    out = []
    for t in ([token.replace(',', '.'), token.replace(',', '')] if ',' in token else [token]):
        mantissa = re.split('[eE]', t)[0]
        out.append((float(t), len(mantissa.split('.')[1]) if '.' in mantissa else 0))
    return out


def _walk(obj, out):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(v for m in IN_RESULTS.finditer(obj) for v, _ in _readings(m.group(0)))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk(str(k), out)
            _walk(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out)


def _hemispheres(obj):
    """(value, letter) pairs from coordinate strings in the results, such as '54.914 N, 60.615 E'."""
    text = json.dumps(obj, ensure_ascii=False)
    return [(float(v.replace(',', '.')), 'W' if h == 'O' else h) for v, h in COORD.findall(text)]


def check_report(text, results):
    """Match the report's numbers and hemispheres against `results` (any JSON: tool results, case facts)."""
    pool = []
    _walk(results, pool)
    known_coords = _hemispheres(results)
    skip = {m.start(1) for m in LIST_MARKER.finditer(text)} | {m.start(1) for m in SIGMA.finditer(text)}
    orphans, numbers = [], 0
    for m in NUMBER.finditer(text):
        if m.start() in skip:
            continue
        numbers += 1
        if not any(abs(abs(v) - abs(x)) <= 0.5 * 10 ** (-d) + 1e-9 for x, d in _readings(m.group(0)) for v in pool):
            orphans.append(m.group(0))
    mismatches = []
    for v, h in COORD.findall(text):
        x, d = _readings(v)[0]
        h = 'W' if h == 'O' else h
        same = [k for val, k in known_coords if abs(val - x) <= 0.5 * 10 ** (-d) + 1e-9]
        if same and h not in same:
            mismatches.append(f'{v} {h} (the tool results say {same[0]})')
    return {'passed': not orphans and not mismatches, 'numbers': numbers, 'traced': numbers - len(orphans),
            'orphans': orphans, 'hemisphere_mismatches': mismatches}
