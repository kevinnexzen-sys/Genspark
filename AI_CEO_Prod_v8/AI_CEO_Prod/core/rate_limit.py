from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

_BUCKETS: Dict[str, Deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, limit: int = 60, window_seconds: int = 60) -> bool:
    now = time.time()
    bucket = _BUCKETS[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True
