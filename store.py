import threading
from typing import Any, Optional

class Cache:
    def __init__(self) -> None:
        self._d: dict[str, Any] = {}
        self._lock = threading.RLock()

    def get(self, k: str, default: Optional[Any] = None) -> Any:
        with self._lock:
            return self._d.get(k, default)

    def set(self, k: str, v: Any) -> None:
        with self._lock:
            self._d[k] = v

    def pop(self, k: str, default: Optional[Any] = None) -> Any:
        with self._lock:
            return self._d.pop(k, default)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

cache = Cache()
