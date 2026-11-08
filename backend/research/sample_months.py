"""Draw one random calendar month per year (2020–2026) for the sampled backtest.

The draw is made once with a fixed, published seed before any results are computed, and the
same months are used for every strategy and both indices.

Eligible months are those with complete data for *both* indices and real option surfaces:
* 2020: May–Dec (NSE bhavcopies in our archive start 13 Apr 2020)
* 2021–2025: Jan–Dec
* 2026: Jan–Mar (Bank Nifty 1-minute data ends 22 Apr 2026)
"""

from __future__ import annotations

import json

import numpy as np

SEED = 20261108
ELIGIBLE = {
    2020: list(range(5, 13)),
    **{y: list(range(1, 13)) for y in range(2021, 2026)},
    2026: [1, 2, 3],
}


def draw() -> dict[int, int]:
    rng = np.random.default_rng(SEED)
    return {y: int(rng.choice(m)) for y, m in ELIGIBLE.items()}


if __name__ == "__main__":
    print(json.dumps(draw()))


# ───────────── Stage 2: one NEW month per year, excluding the stage-1 months ─────────────
SEED_STAGE2 = 20261109


def stage2_eligible() -> dict[int, list[int]]:
    used = draw()
    return {y: [m for m in ms if m != used[y]] for y, ms in ELIGIBLE.items()}


def draw_stage2() -> dict[int, int]:
    rng = np.random.default_rng(SEED_STAGE2)
    return {y: int(rng.choice(m)) for y, m in stage2_eligible().items()}
