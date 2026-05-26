import asyncio
import time
from typing import Dict, List


class KeyManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._keys: Dict[str, List[dict]] = {}
        self._index: Dict[str, int] = {}

    def load_keys(self, provider_name: str, keys: list[str]):
        self._keys[provider_name] = [{"key": k, "disabled_until": 0, "fail_count": 0} for k in keys if k]
        self._index[provider_name] = 0

    async def get_key(self, provider_name: str) -> str | None:
        async with self._lock:
            keys = self._keys.get(provider_name, [])
            if not keys:
                return None
            now = time.time()
            for _ in range(len(keys)):
                idx = self._index.get(provider_name, 0) % len(keys)
                entry = keys[idx]
                self._index[provider_name] = idx + 1
                if entry["disabled_until"] <= now:
                    return entry["key"]
            return min(keys, key=lambda e: e["disabled_until"])["key"]

    async def mark_success(self, provider_name: str, key: str):
        async with self._lock:
            for entry in self._keys.get(provider_name, []):
                if entry["key"] == key:
                    entry["fail_count"] = 0
                    entry["disabled_until"] = 0
                    break

    async def mark_failure(self, provider_name: str, key: str):
        async with self._lock:
            for entry in self._keys.get(provider_name, []):
                if entry["key"] == key:
                    entry["fail_count"] += 1
                    entry["disabled_until"] = time.time() + min(5 * (3 ** (entry["fail_count"] - 1)), 300)
                    break

    def get_status(self, provider_name: str) -> list[dict]:
        now = time.time()
        return [{"key_masked": e["key"][:8] + "..." + e["key"][-4:] if len(e["key"]) > 16 else e["key"][:4] + "...", "fail_count": e["fail_count"], "disabled": e["disabled_until"] > now, "recover_in": max(0, int(e["disabled_until"] - now))} for e in self._keys.get(provider_name, [])]
