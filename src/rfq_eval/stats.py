"""Confidence intervals for case-level pass rates.

The interval treats cases as independent Bernoulli trials. Cells and lines
inside one RFQ are not independent, so item counts must not be passed to this
function when reporting a production claim.
"""

import math
from decimal import Decimal

from rfq_eval.thresholds import WILSON_Z


def wilson_interval(successes: int, n: int, z: float = WILSON_Z) -> tuple[Decimal, Decimal]:
    if n <= 0:
        raise ValueError("Wilson interval requires a positive sample size")
    if successes < 0 or successes > n:
        raise ValueError("successes must lie between 0 and n")
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) / n) + (z2 / (4 * n * n))) / denom
    low = max(0.0, center - margin)
    high = min(1.0, center + margin)
    return (Decimal(f"{low:.6f}"), Decimal(f"{high:.6f}"))


def ratio(numer: int, denom: int) -> Decimal:
    if denom <= 0:
        raise ValueError("ratio requires a positive denominator")
    return (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.000001"))


def p95_nearest_rank(samples: list[Decimal]) -> Decimal:
    if not samples:
        raise ValueError("p95 requires samples")
    ordered = sorted(samples)
    index = math.ceil(0.95 * len(ordered)) - 1
    return ordered[index]
