"""Natural meteoroid or re-entering spacecraft, decided from speed and its uncertainty.

Anything bound to the Sun hits the atmosphere faster than Earth's escape speed (11.2 km/s);
re-entering satellites and rocket stages arrive below orbital speed (about 7.8 km/s), slowly and for long.
The rule reads a 95% speed range: the Monte Carlo's 2.5 and 97.5 percentiles when one exists, else speed +/- 2 sigma.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Verdict:
    kind: str  # natural | reentry | inconclusive
    reason: str
    meteorites_possible: bool
    band: tuple = ()  # the 95% speed range the rule read, km/s


def decide(speed_kms, sigma_kms, duration_s=None, slow_fragments=False, slope_deg=None,
           end_height_km=None, end_speed_kms=None, band=None, band_source=None):
    lo, hi = band if band else (speed_kms - 2 * sigma_kms, speed_kms + 2 * sigma_kms)
    said = (f'{speed_kms:.1f} km/s, 95% range {lo:.1f} to {hi:.1f} km/s' + (f' ({band_source})' if band_source else '')
            if band else f'{speed_kms:.1f} ± {sigma_kms:.1f} km/s')
    long_and_slow = (duration_s or 0) > 20 or slow_fragments or (slope_deg is not None and slope_deg < 10)
    if lo > 11.0:
        kind, reason = 'natural', f'{said} is above escape speed'
    elif hi < 8.5 and long_and_slow:
        kind, reason = 'reentry', f'{said} is below orbital speed and the passage is long'
    else:
        kind, reason = 'inconclusive', f'{said} does not separate the two cases'
    survives = (kind == 'natural' and end_height_km is not None and end_height_km <= 30
                and (end_speed_kms is None or end_speed_kms <= 8))
    return Verdict(kind, reason, survives, (round(lo, 2), round(hi, 2)))
