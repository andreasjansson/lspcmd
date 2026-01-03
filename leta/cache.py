import logging
import pickle
import time
from pathlib import Path
from typing import TypeVar

import lmdb

logger = logging.getLogger(__name__)

K = TypeVar("K")
V = TypeVar("V")


class CacheEntry:
    """Typed wrapper for cache entry data."""
    value: object
    access_time: float
    size: int

    def __init__(self, value: object, access_time: float, size: int = 0):
        self.value = value
        self.access_time = access_time
        self.size = size

    def to_dict(self) -> dict[str, object]:
        return {"value": self.value, "access_time": self.access_time, "size": self.size}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CacheEntry":
        access_time_raw = data.get("access_time", 0)
        size_raw = data.get("size", 0)
        return cls(
            value=data["value"],
            access_time=float(access_time_raw) if access_time_raw else 0.0,
            size=int(size_raw) if size_raw else 0,
        )


class LMDBCache:
    """LRU cache backed by LMDB for persistence."""

    path: Path
    max_bytes: int
    env: lmdb.Environment  # type: ignore[name-defined]
    order: list[bytes]
    sizes: dict[bytes, int]
    current_bytes: int
    _entry_count: int

    def __init__(self, path: Path, max_bytes: int):
        self.path = path
        self.max_bytes = max_bytes
        self.path.mkdir(parents=True, exist_ok=True)

        self.env = lmdb.open(  # type: ignore[attr-defined]
            str(path),
            map_size=max(max_bytes * 2, 1024 * 1024),
            max_dbs=1,
            writemap=True,
            map_async=True,
        )

        self.order = []
        self.sizes = {}
        self.current_bytes = 0
        self._entry_count = 0

        self._load_metadata()

    def _load_metadata(self) -> None:
        entries: list[tuple[bytes, float, int]] = []

        with self.env.begin() as txn:  # type: ignore[union-attr]
            cursor = txn.cursor()  # type: ignore[union-attr]
            for key_bytes, value_bytes in cursor:
                try:
                    raw_entry: dict[str, object] = pickle.loads(value_bytes)
                    entry = CacheEntry.from_dict(raw_entry)
                    entries.append((key_bytes, entry.access_time, entry.size or len(value_bytes)))
                except Exception as e:
                    logger.warning(f"Failed to load cache entry: {e}")

        entries.sort(key=lambda x: x[1])

        self.order = [e[0] for e in entries]
        self.sizes = {e[0]: e[2] for e in entries}
        self.current_bytes = sum(self.sizes.values())
        self._entry_count = len(self.order)

        logger.info(
            f"Loaded {self._entry_count} cache entries "
            + f"({self.current_bytes / 1024 / 1024:.1f}MB) from {self.path}"
        )

    def __len__(self) -> int:
        return self._entry_count

    def __contains__(self, key: tuple[object, ...]) -> bool:
        key_bytes = pickle.dumps(key)
        with self.env.begin() as txn:  # type: ignore[union-attr]
            return txn.get(key_bytes) is not None  # type: ignore[union-attr]

    def get(self, key: tuple[object, ...], default: object = None) -> object:
        key_bytes = pickle.dumps(key)

        with self.env.begin(write=True) as txn:  # type: ignore[union-attr]
            value_bytes: bytes | None = txn.get(key_bytes)  # type: ignore[union-attr]
            if value_bytes is None:
                return default

            try:
                raw_entry: dict[str, object] = pickle.loads(value_bytes)
                entry = CacheEntry.from_dict(raw_entry)
                entry.access_time = time.time()
                txn.put(key_bytes, pickle.dumps(entry.to_dict()))  # type: ignore[union-attr]

                if key_bytes in self.sizes:
                    self.order.remove(key_bytes)
                    self.order.append(key_bytes)

                return entry.value
            except Exception as e:
                logger.warning(f"Failed to read cache entry: {e}")
                return default

    def __getitem__(self, key: tuple[object, ...]) -> object:
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result

    def __setitem__(self, key: tuple[object, ...], value: object) -> None:
        key_bytes = pickle.dumps(key)
        entry = CacheEntry(value=value, access_time=time.time(), size=0)
        value_bytes = pickle.dumps(entry.to_dict())
        entry.size = len(value_bytes)
        value_bytes = pickle.dumps(entry.to_dict())
        value_size = len(value_bytes)

        with self.env.begin(write=True) as txn:  # type: ignore[union-attr]
            if key_bytes in self.sizes:
                old_size = self.sizes[key_bytes]
                self.current_bytes -= old_size
                self.order.remove(key_bytes)
                self._entry_count -= 1

            while self.order and (self.current_bytes + value_size) > self.max_bytes:
                oldest = self.order.pop(0)
                self.current_bytes -= self.sizes[oldest]
                del self.sizes[oldest]
                txn.delete(oldest)  # type: ignore[union-attr]
                self._entry_count -= 1

            txn.put(key_bytes, value_bytes)  # type: ignore[union-attr]
            self.sizes[key_bytes] = value_size
            self.current_bytes += value_size
            self.order.append(key_bytes)
            self._entry_count += 1

    def close(self) -> None:
        self.env.close()  # type: ignore[union-attr]
