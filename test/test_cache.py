import pickle
import time
from pathlib import Path

import pytest

from lspcmd.cache import LMDBCache


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "test_cache.lmdb"


class TestLMDBCacheBasicOperations:
    def test_set_and_get(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = "value1"
            assert cache.get(("key1",)) == "value1"
        finally:
            cache.close()

    def test_get_missing_key_returns_default(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            assert cache.get(("missing",)) is None
            assert cache.get(("missing",), "default") == "default"
        finally:
            cache.close()

    def test_contains(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = "value1"
            assert ("key1",) in cache
            assert ("missing",) not in cache
        finally:
            cache.close()

    def test_len(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            assert len(cache) == 0
            cache[("key1",)] = "value1"
            assert len(cache) == 1
            cache[("key2",)] = "value2"
            assert len(cache) == 2
        finally:
            cache.close()

    def test_overwrite_existing_key(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = "value1"
            cache[("key1",)] = "value2"
            assert cache.get(("key1",)) == "value2"
            assert len(cache) == 1
        finally:
            cache.close()

    def test_complex_keys_and_values(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("path/to/file.py", 42, "abc123")] = {"name": "foo", "items": [1, 2, 3]}
            result = cache.get(("path/to/file.py", 42, "abc123"))
            assert result == {"name": "foo", "items": [1, 2, 3]}
        finally:
            cache.close()


class TestLMDBCacheLRUEviction:
    def _entry_size(self, key: tuple, value) -> int:
        entry = {"value": value, "access_time": 0.0, "size": 0}
        value_bytes = pickle.dumps(entry)
        entry["size"] = len(value_bytes)
        return len(pickle.dumps(entry))

    def test_evicts_oldest_when_full(self, cache_dir):
        size_per_entry = self._entry_size(("k",), "x" * 10)
        max_bytes = size_per_entry * 2 + 10
        
        cache = LMDBCache(cache_dir, max_bytes=max_bytes)
        try:
            cache[("key1",)] = "x" * 10
            cache[("key2",)] = "x" * 10
            assert len(cache) == 2
            assert ("key1",) in cache
            assert ("key2",) in cache
            
            cache[("key3",)] = "x" * 10
            
            assert len(cache) == 2
            assert ("key1",) not in cache
            assert ("key2",) in cache
            assert ("key3",) in cache
        finally:
            cache.close()

    def test_access_updates_lru_order(self, cache_dir):
        size_per_entry = self._entry_size(("k",), "x" * 10)
        max_bytes = size_per_entry * 2 + 10
        
        cache = LMDBCache(cache_dir, max_bytes=max_bytes)
        try:
            cache[("key1",)] = "x" * 10
            time.sleep(0.01)
            cache[("key2",)] = "x" * 10
            
            time.sleep(0.01)
            cache.get(("key1",))
            
            time.sleep(0.01)
            cache[("key3",)] = "x" * 10
            
            assert ("key1",) in cache
            assert ("key2",) not in cache
            assert ("key3",) in cache
        finally:
            cache.close()

    def test_evicts_multiple_entries_if_needed(self, cache_dir):
        small_size = self._entry_size(("k",), "x")
        large_size = self._entry_size(("k",), "x" * 100)
        max_bytes = small_size * 3 + 10
        
        cache = LMDBCache(cache_dir, max_bytes=max_bytes)
        try:
            cache[("key1",)] = "x"
            cache[("key2",)] = "x"
            cache[("key3",)] = "x"
            assert len(cache) == 3
            
            cache[("key4",)] = "x" * 100
            
            assert ("key4",) in cache
            remaining = sum(1 for k in [("key1",), ("key2",), ("key3",)] if k in cache)
            assert remaining < 3
        finally:
            cache.close()

    def test_current_bytes_tracking(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            assert cache.current_bytes == 0
            
            cache[("key1",)] = "value1"
            bytes_after_one = cache.current_bytes
            assert bytes_after_one > 0
            
            cache[("key2",)] = "value2"
            bytes_after_two = cache.current_bytes
            assert bytes_after_two > bytes_after_one
            
            cache[("key1",)] = "new_value"
            assert cache.current_bytes != bytes_after_two
        finally:
            cache.close()


class TestLMDBCachePersistence:
    def test_survives_close_and_reopen(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = "value1"
            cache[("key2",)] = {"nested": "data"}
        finally:
            cache.close()
        
        cache2 = LMDBCache(cache_dir, max_bytes=10000)
        try:
            assert cache2.get(("key1",)) == "value1"
            assert cache2.get(("key2",)) == {"nested": "data"}
            assert len(cache2) == 2
        finally:
            cache2.close()

    def test_lru_order_survives_restart(self, cache_dir):
        size_per_entry = 100
        
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = "a"
            time.sleep(0.01)
            cache[("key2",)] = "b"
            time.sleep(0.01)
            cache[("key3",)] = "c"
            
            time.sleep(0.01)
            cache.get(("key1",))
            
            bytes_before = cache.current_bytes
        finally:
            cache.close()
        
        cache2 = LMDBCache(cache_dir, max_bytes=bytes_before + 50)
        try:
            time.sleep(0.01)
            cache2[("key4",)] = "d"
            
            assert ("key1",) in cache2
            assert ("key3",) in cache2
            assert ("key4",) in cache2
            assert ("key2",) not in cache2
        finally:
            cache2.close()

    def test_current_bytes_restored_on_reload(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = "value1"
            cache[("key2",)] = "value2"
            bytes_before = cache.current_bytes
            count_before = len(cache)
        finally:
            cache.close()
        
        cache2 = LMDBCache(cache_dir, max_bytes=10000)
        try:
            assert cache2.current_bytes == bytes_before
            assert len(cache2) == count_before
        finally:
            cache2.close()


class TestLMDBCacheEdgeCases:
    def test_empty_cache(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            assert len(cache) == 0
            assert cache.current_bytes == 0
            assert cache.get(("missing",)) is None
        finally:
            cache.close()

    def test_none_value(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = None
            assert ("key1",) in cache
            assert cache.get(("key1",), "default") is None
        finally:
            cache.close()

    def test_empty_string_value(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("key1",)] = ""
            assert cache.get(("key1",)) == ""
        finally:
            cache.close()

    def test_large_value(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=1024 * 1024)
        try:
            large_value = "x" * 100000
            cache[("key1",)] = large_value
            assert cache.get(("key1",)) == large_value
        finally:
            cache.close()

    def test_many_entries(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=1024 * 1024)
        try:
            for i in range(1000):
                cache[(f"key{i}",)] = f"value{i}"
            
            assert len(cache) == 1000
            assert cache.get(("key0",)) == "value0"
            assert cache.get(("key999",)) == "value999"
        finally:
            cache.close()

    def test_tuple_key_with_various_types(self, cache_dir):
        cache = LMDBCache(cache_dir, max_bytes=10000)
        try:
            cache[("str", 123, 45.6, True, None)] = "complex_key"
            assert cache.get(("str", 123, 45.6, True, None)) == "complex_key"
        finally:
            cache.close()
