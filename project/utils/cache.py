import time
from typing import Dict, Any, Optional, Tuple

class Cache:
    def __init__(self, timeout: int = 300):
        self.cache: Dict[str, Tuple[float, Any]] = {}
        self.timeout = timeout

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        if key in self.cache:
            timestamp, value = self.cache[key]
            if time.time() - timestamp < self.timeout:
                return value
            else:
                del self.cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp"""
        self.cache[key] = (time.time(), value)
        self._cleanup()

    def _cleanup(self) -> None:
        """Remove expired entries from cache"""
        current_time = time.time()
        expired_keys = [
            k for k, v in self.cache.items()
            if current_time - v[0] > self.timeout
        ]
        for k in expired_keys:
            del self.cache[k]

    def clear(self) -> None:
        """Clear all cache entries"""
        self.cache.clear() 