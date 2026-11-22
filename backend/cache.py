"""Boyut sinirli, sureli (TTL) ve thread-safe bellek ici onbellek."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """
    En fazla `max_entries` kayit tutar; dolunca en uzun suredir kullanilmayan kaydi atar (LRU).
    Boylece uzun sure acik kalan sunucuda bellek sinirsiz buyumez.
    """

    def __init__(self, max_entries: int = 64) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if (time.time() - entry[0]) >= ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return entry[1]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
