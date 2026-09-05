"""Stage 5 [MOCKED] — stands in for a real production traffic hook.

Simulates sampled live input/output pairs by calling the deployed
('modernized') implementation directly at intervals. A real deployment would
replace this with a log-tailing or traffic-mirroring integration."""

import random
from typing import Callable


def sample_traffic(
    impl_fn: Callable[..., dict],
    field_bounds: dict[str, tuple[float, float]],
    n_samples: int = 50,
    seed: int | None = None,
) -> list[dict]:
    rng = random.Random(seed)
    samples = []
    for _ in range(n_samples):
        inputs = {
            f: (int(rng.uniform(lo, hi)) if (isinstance(lo, int) and isinstance(hi, int)) else rng.uniform(lo, hi))
            for f, (lo, hi) in field_bounds.items()
        }
        output = impl_fn(**inputs)
        samples.append({"inputs": inputs, "output": output})
    return samples
