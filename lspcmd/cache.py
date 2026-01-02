import logging
import pickle
import time
from pathlib import Path
from typing import Any

import lmdb

logger = logging.getLogger(__name__)


class LMDBCache:
    def __init__(self, path: Path, max_bytes: int):
        self.path = path
        self.max_bytes = max_bytes
        self.path.mkdir(parents=True, exist_ok=True)
        
        self.env = lmdb.open(
            str(path),
            map_size=max(max_bytes * 2, 1024 * 1024),
            max_dbs=1,
            writemap=True,
            map_async=True,
        )
        
        self.order: list[bytes] = []
        self.sizes: dict[bytes, int] = {}
        self.current_bytes = 0
        self._entry_count = 0
        
        self._load_metadata()

    def _load_metadata(self) -> None:
        entries: list[tuple[bytes, float, int]] = []
        
        with self.env.begin() as txn:
            cursor = txn.cursor()
            for key_bytes, value_bytes in cursor:
                try:
                    entry = pickle.loads(value_bytes)
                    access_time = entry.get("access_time", 0)
                    size = entry.get("size", len(value_bytes))
                    entries.append((key_bytes, access_time, size))
                except Exception as e:
                    logger.warning(f"Failed to load cache entry: {e}")
        
        entries.sort(key=lambda x: x[1])
        
        self.order = [e[0] for e in entries]
        self.sizes = {e[0]: e[2] for e in entries}
        self.current_bytes = sum(self.sizes.values())
        self._entry_count = len(self.order)
        
        logger.info(
            f"Loaded {self._entry_count} cache entries "
            f"({self.current_bytes / 1024 / 1024:.1f}MB) from {self.path}"
        )

    def __len__(self) -> int:
        return self._entry_count

    def __contains__(self, key: tuple[Any, ...]) -> bool:
        key_bytes = pickle.dumps(key)
        with self.env.begin() as txn:
            return txn.get(key_bytes) is not None

    def get(self, key: tuple[Any, ...], default: Any = None) -> Any:
        key_bytes = pickle.dumps(key)
        
        with self.env.begin(write=True) as txn:
            value_bytes = txn.get(key_bytes)
            if value_bytes is None:
                return default
            
            try:
                entry = pickle.loads(value_bytes)
                entry["access_time"] = time.time()
                txn.put(key_bytes, pickle.dumps(entry))
                
                if key_bytes in self.sizes:
                    self.order.remove(key_bytes)
                    self.order.append(key_bytes)
                
                return entry["value"]
            except Exception as e:
                logger.warning(f"Failed to read cache entry: {e}")
                return default

    def __getitem__(self, key: tuple) -> Any:
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result

    def __setitem__(self, key: tuple, value: Any) -> None:
        key_bytes = pickle.dumps(key)
        entry = {
            "value": value,
            "access_time": time.time(),
            "size": 0,
        }
        value_bytes = pickle.dumps(entry)
        entry["size"] = len(value_bytes)
        value_bytes = pickle.dumps(entry)
        value_size = len(value_bytes)
        
        with self.env.begin(write=True) as txn:
            if key_bytes in self.sizes:
                old_size = self.sizes[key_bytes]
                self.current_bytes -= old_size
                self.order.remove(key_bytes)
                self._entry_count -= 1
            
            while self.order and (self.current_bytes + value_size) > self.max_bytes:
                oldest = self.order.pop(0)
                self.current_bytes -= self.sizes[oldest]
                del self.sizes[oldest]
                txn.delete(oldest)
                self._entry_count -= 1
            
            txn.put(key_bytes, value_bytes)
            self.sizes[key_bytes] = value_size
            self.current_bytes += value_size
            self.order.append(key_bytes)
            self._entry_count += 1

    def close(self) -> None:
        self.env.close()
