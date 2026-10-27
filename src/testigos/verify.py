"""Every number in a report has to come from a tool result of the same run, as the same kind of quantity.

Muse Spark writes the report from the tool results; this check sits inside write_report, so the model cannot skip it
(the pattern of Meta's agent workshop: checks outside the model, at the points that matter). It takes each number in
the text (decimal comma or point, ranges, dates, scientific notation) with the unit printed after it, and matches it
against the tool results within the precision the text prints. A number with a unit (km/s, km, degrees, seconds, a
percentage) must match a result of that kind: "66.3 km/s" fails when 66.3 is an angle in degrees. A bare number may
match any result. Hemisphere letters next to a coordinate must agree with the results, and the verdict the text states
(a natural meteoroid, a re-entering satellite) must be the one the code computed.
It catches invented, mistyped or misattributed figures, swapped hemispheres and a contradicted verdict. It does not
judge other qualitative claims, and a bare small integer can still match an unrelated result.
"""
from __future__ import annotations

import json
import re

NUMBER = re.compile(r'(?<![\w.])\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?')
IN_RESULTS = re.compile(r'\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?')  # also digits after a letter, such as the hour in '...T03:50:24Z'
COORD = re.compile(r'(\d+(?:[.,]\d+)?)\s*°?\s*([NSEWO])\b')
LIST_MARKER = re.compile(r'^\s*(\d+)[.)]\s', re.M)  # '1. ' starting a line numbers a list, it is not a figure
SIGMA = re.compile(r'(?<![\w.])([123])\s*(?:σ|sigma)')  # the 1 in '1σ' names a range, it is not a figure

# The unit printed right after a number. Hemisphere letters are upper case only, so 's' stays seconds.
UNIT = re.compile(
    r'\s*(?:'
    r'(?P<speed>(?i:km\s*/\s*s\b|kil[oó]metros?\s+por\s+segundo\b|kilomet(?:er|re)s?\s+(?:per|a)\s+second\b))'
    r'|(?P<km>(?i:km\b|kil[oó]metros?\b|kilomet(?:er|re)s?\b))'
    r'|(?P<angle>°|º|(?i:grados?\b|degrees?\b|deg\b)|[NSEWO]\b)'
    r'|(?P<seconds>(?i:s\b|seg\b|segundos?\b|seconds?\b))'
    r'|(?P<percent>%|(?i:por\s+ciento\b|percent\b))'
    r')')
RANGE_TO = re.compile(r'\s*(?:-|–|—|(?i:to|a|y|and|hasta))\s*(?=\d)')  # '15.6–21.6 km/s': the first number shares the unit

# A verdict stated in the text: '... so it was a re-entering satellite', 'fue un meteoroide natural'. Questions and
# negations ('whether it was a meteor', 'no fue un satélite') are not claims.
_NOT = r'(?<![Nn]o )(?<![Nn]ot )(?<![Ww]hether it )(?<![Ii]f it )(?<![Ss]i )'
CLAIMS = {
    'reentry': [
        re.compile(_NOT + r"\b(?i:was|is|it's)\s+(?i:an?\s+|the\s+)?(?i:re-?entering|re-?entry|man-made|artificial|space\s+(?:junk|debris)|satellite|rocket)\b"),
        re.compile(_NOT + r"\b(?i:fue|era|es|se\s+trató\s+de)\s+(?i:un\s+|una\s+|el\s+|la\s+)?(?i:reingreso|satélite|cohete|basura\s+espacial|chatarra\s+espacial|desecho\s+espacial|objeto\s+artificial)\b"),
    ],
    'natural': [
        re.compile(_NOT + r"\b(?i:was|is|it's)\s+(?i:an?\s+)?(?i:natural|meteor|meteoroid|asteroid|asteroidal|rock\s+from\s+space)\b"),
        re.compile(r"\b(?i:natural\s+(?:origin|meteor|meteoroid|object|body))\b"),
        re.compile(_NOT + r"\b(?i:fue|era|es)\s+(?i:un\s+|una\s+)?(?i:meteoro|meteoroide|asteroide|roca\s+espacial|objeto\s+natural)\b"),
        re.compile(r"\b(?i:origen\s+natural)\b"),
    ],
}


def _readings(token):
    """A token's value and printed decimals; with a comma, both the decimal-comma and the thousands reading."""
    out = []
    for t in ([token.replace(',', '.'), token.replace(',', '')] if ',' in token else [token]):
        mantissa = re.split('[eE]', t)[0]
        out.append((float(t), len(mantissa.split('.')[1]) if '.' in mantissa else 0))
    return out


def _unit_at(text, pos):
    m = UNIT.match(text, pos)
    if not m:
        return None
    return next(k for k, v in m.groupdict().items() if v is not None)


def _units(text, matches):
    """The unit of each number match: the one printed after it, or after the next number when the two make a range."""
    units = [_unit_at(text, m.end()) for m in matches]
    for i in range(len(matches) - 2, -1, -1):
        if units[i] is None and units[i + 1] and RANGE_TO.fullmatch(text, matches[i].end(), matches[i + 1].start()):
            units[i] = units[i + 1]
    return units


def _key_class(key):
    k = key.lower()
    if 'kms' in k or 'speed' in k:
        return 'speed'
    if '_deg' in k or k.endswith('deg') or k in ('azimuth', 'slope', 'hfov'):
        return 'angle'
    if k.endswith('_km') or 'height' in k:
        return 'km'
    if k.endswith('_s') or 'duration' in k or 'seen_for' in k:
        return 'seconds'
    return None


def _walk(obj, out, kind=None):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append((float(obj), kind))
    elif isinstance(obj, str):
        ms = list(IN_RESULTS.finditer(obj))
        for m, unit in zip(ms, _units(obj, ms)):
            out.extend((v, unit or kind) for v, _ in _readings(m.group(0)))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk(str(k), out)  # keys such as clip ids are bare numbers
            _walk(v, out, _key_class(str(k)) or kind)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out, kind)


def _hemispheres(obj):
    """(value, letter) pairs from coordinate strings in the results, such as '54.914 N, 60.615 E'."""
    text = json.dumps(obj, ensure_ascii=False)
    return [(float(v.replace(',', '.')), 'W' if h == 'O' else h) for v, h in COORD.findall(text)]


def verdict_claims(text):
    """The verdicts the text states as facts: a subset of {'natural', 'reentry'}."""
    return {kind for kind, pats in CLAIMS.items() if any(p.search(text) for p in pats)}


def check_report(text, results, verdict=None):
    """Match the report's numbers, hemispheres and, when `verdict` is given, its stated verdict against `results`.

    `verdict` is the code's verdict ('natural', 'reentry', 'inconclusive'), or 'none' when there is no trajectory.
    """
    pool = []
    _walk(results, pool)
    known_coords = _hemispheres(results)
    skip = {m.start(1) for m in LIST_MARKER.finditer(text)} | {m.start(1) for m in SIGMA.finditer(text)}
    matches = [m for m in NUMBER.finditer(text) if m.start() not in skip]
    orphans, numbers, wrong_kind = [], 0, []
    for m, unit in zip(matches, _units(text, matches)):
        numbers += 1
        readings = _readings(m.group(0))

        def found(kind=None):
            return any(abs(abs(v) - abs(x)) <= 0.5 * 10 ** (-d) + 1e-9 for x, d in readings for v, k in pool
                       if kind is None or k == kind)
        if unit and not found(unit):
            orphans.append(m.group(0))
            if found():  # the value exists, but as another quantity: '66.3 km/s' where 66.3 is an angle
                wrong_kind.append(f'{m.group(0)} ({unit})')
        elif not unit and not found():
            orphans.append(m.group(0))
    mismatches = []
    for v, h in COORD.findall(text):
        x, d = _readings(v)[0]
        h = 'W' if h == 'O' else h
        same = [k for val, k in known_coords if abs(val - x) <= 0.5 * 10 ** (-d) + 1e-9]
        if same and h not in same:
            mismatches.append(f'{v} {h} (the tool results say {same[0]})')
    verdict_wrong = []
    if verdict is not None:
        verdict_wrong = sorted(k for k in verdict_claims(text) if k != verdict)
    return {'passed': not orphans and not mismatches and not verdict_wrong, 'numbers': numbers,
            'traced': numbers - len(orphans), 'orphans': orphans, 'wrong_kind': wrong_kind,
            'hemisphere_mismatches': mismatches, 'verdict_mismatches': verdict_wrong}
