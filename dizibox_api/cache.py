"""Thread-safe in-memory TTL Cache with stats and eviction."""

import time
from threading import RLock
from typing import Any, Optional, Dict


class TTLCache:
    def __init__(self, default_ttl: int = 300, maxsize: int = 1000):
        self.default_ttl = default_ttl
        self.maxsize = maxsize
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._lock = RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            now = time.time()
            if key in self._cache:
                expires_at, val = self._cache[key]
                if expires_at > now:
                    self._hits += 1
                    return val
                else:
                    del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            now = time.time()
            expire_duration = ttl if ttl is not None else self.default_ttl
            expires_at = now + expire_duration

            if len(self._cache) >= self.maxsize:
                # Evict expired keys
                expired_keys = [k for k, (exp, _) in self._cache.items() if exp <= now]
                for k in expired_keys:
                    del self._cache[k]
                # If still full, pop first key
                if len(self._cache) >= self.maxsize:
                    first_key = next(iter(self._cache))
                    del self._cache[first_key]

            self._cache[key] = (expires_at, value)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            ratio = (self._hits / total * 100) if total > 0 else 0.0
            return {
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio_percent": round(ratio, 2)
            }
