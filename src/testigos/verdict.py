"""Natural meteoroid or re-entering spacecraft, decided from speed and its uncertainty.

Anything bound to the Sun hits the atmosphere faster than Earth's escape speed (11.2 km/s);
re-entering satellites and rocket stages arrive below orbital speed (about 7.8 km/s), slowly and for long.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Verdict:
    kind: str  # natural | reentry | inconclusive
    reason: str
    meteorites_possible: bool


def decide(speed_kms, sigma_kms, duration_s=None, slow_fragments=False, slope_deg=None,
           end_height_km=None, end_speed_kms=None):
    lo, hi = speed_kms - 2 * sigma_kms, speed_kms + 2 * sigma_kms
    long_and_slow = (duration_s or 0) > 20 or slow_fragments or (slope_deg is not None and slope_deg < 10)
    if lo > 11.0:
        kind, reason = 'natural', f'{speed_kms:.1f} ± {sigma_kms:.1f} km/s is above escape speed'
    elif hi < 8.5 and long_and_slow:
        kind, reason = 'reentry', f'{speed_kms:.1f} ± {sigma_kms:.1f} km/s is below orbital speed and the passage is long'
    else:
        kind, reason = 'inconclusive', f'{speed_kms:.1f} ± {sigma_kms:.1f} km/s does not separate the two cases'
    survives = (kind == 'natural' and end_height_km is not None and end_height_km <= 30
                and (end_speed_kms is None or end_speed_kms <= 8))
    return Verdict(kind, reason, survives)
