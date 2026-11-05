"""Intervalle und Perzentile für die KPI-Suite (nur Standardbibliothek, deterministisch).

- Anteile (Ja/Nein je Frage): 95-%-Wilson-Intervall. Es bleibt auch bei kleinem n und Anteilen nahe 0 oder 1 im
  Bereich [0, 1], anders als das Normalapproximations-Intervall (Brown, Cai & DasGupta 2001).
- Mittelwerte und Perzentile (Latenz, Schritte, Tokens/s, anteilige Werte wie Recall@k): Perzentil-Bootstrap mit
  festem Seed (Efron & Tibshirani 1993), damit derselbe Lauf immer dasselbe Intervall ergibt.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

Z95 = 1.959963984540054
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 7


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """95-%-Wilson-Intervall für einen Anteil; None bei n = 0."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Perzentil mit linearer Interpolation (wie numpy 'linear'); q in [0, 100]."""
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q / 100.0
    low, high = math.floor(pos), math.ceil(pos)
    return data[low] + (data[high] - data[low]) * (pos - low)


def mean(values: Sequence[float]) -> float | None:
    data = [float(v) for v in values]
    return sum(data) / len(data) if data else None


def bootstrap(values: Sequence[float], statistic: Callable[[Sequence[float]], float | None] = mean,
              samples: int = BOOTSTRAP_SAMPLES, seed: int = BOOTSTRAP_SEED) -> tuple[float, float] | None:
    """95-%-Perzentil-Bootstrap-Intervall einer Statistik; None bei weniger als zwei Werten."""
    data = [float(v) for v in values]
    if len(data) < 2:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(samples):
        resample = [data[rng.randrange(len(data))] for _ in data]
        value = statistic(resample)
        if value is not None:
            stats.append(value)
    return percentile(stats, 2.5), percentile(stats, 97.5)


def p50(values: Sequence[float]) -> float | None:
    return percentile(values, 50)


def p95(values: Sequence[float]) -> float | None:
    return percentile(values, 95)
