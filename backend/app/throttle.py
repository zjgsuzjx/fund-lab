"""Bounded, thread-safe throttling for the single-process local server."""
from collections import OrderedDict
from threading import Lock
from time import monotonic
from fastapi import HTTPException, Request

_buckets = OrderedDict()
_lock = Lock()


def throttle(request: Request):
    key = request.client.host if request.client else 'unknown'
    now = monotonic()
    with _lock:
        for old_key in list(_buckets):
            if now - _buckets[old_key][0] >= 60:
                del _buckets[old_key]
        start, count = _buckets.get(key, (now, 0))
        if count >= 30:
            raise HTTPException(429, '操作过于频繁，请一分钟后再试。', headers={'Retry-After': '60'})
        _buckets[key] = (start, count + 1)
        if len(_buckets) > 10000:
            _buckets.popitem(last=False)
