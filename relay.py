import json
import time
import logging
from typing import AsyncIterator, Dict, List, Tuple
from config import config
from key_manager import KeyManager
from providers.base import BaseProvider
from providers.openai import OpenAIProvider
from providers.anthropic import AnthropicProvider

logger = logging.getLogger("relay")

PROVIDER_CLASSES = {"openai": OpenAIProvider, "anthropic": AnthropicProvider, "custom": OpenAIProvider}


class Relay:
    def __init__(self):
        self.key_manager = KeyManager()
        self.providers: Dict[str, BaseProvider] = {}
        self.model_map: Dict[str, str] = {}
        self._usage_log: List[dict] = []
        self._init_providers()

    def _init_providers(self):
        for name, pcfg in config.get("providers", {}).items():
            if not pcfg or not pcfg.get("enabled", False):
                continue
            cls = PROVIDER_CLASSES.get(name, OpenAIProvider)
            base_url = pcfg.get("base_url", "")
            keys = pcfg.get("api_keys", [])
            models = pcfg.get("models", {})
            if not base_url:
                continue
            self.providers[name] = cls(base_url=base_url, api_keys=list(keys), models=models)
            self.key_manager.load_keys(name, keys)
            for display_name in models:
                self.model_map[display_name] = name
                logger.info(f"Registered model: {display_name} -> {name}")

    def _find_provider(self, model: str) -> Tuple[BaseProvider, str]:
        if model in self.model_map:
            name = self.model_map[model]
            return self.providers[name], name
        if self.providers:
            name = next(iter(self.providers))
            return self.providers[name], name
        raise ValueError(f"No provider for model: {model}")

    async def chat(self, model: str, messages: list, **kwargs) -> dict:
        provider, pname = self._find_provider(model)
        key = await self.key_manager.get_key(pname)
        if key:
            provider.api_keys = [key] + [k for k in provider.api_keys if k != key]
        start = time.time()
        try:
            result = await provider.chat(model, messages, **kwargs)
            if key:
                await self.key_manager.mark_success(pname, key)
            self._log_usage(model, pname, result.get("usage", {}), time.time() - start, True)
            return result
        except Exception as e:
            if key:
                await self.key_manager.mark_failure(pname, key)
            self._log_usage(model, pname, {}, time.time() - start, False, str(e))
            raise

    async def chat_stream(self, model: str, messages: list, **kwargs) -> AsyncIterator[dict]:
        provider, pname = self._find_provider(model)
        key = await self.key_manager.get_key(pname)
        if key:
            provider.api_keys = [key] + [k for k in provider.api_keys if k != key]
        start = time.time()
        try:
            async for chunk in provider.chat_stream(model, messages, **kwargs):
                yield chunk
            if key:
                await self.key_manager.mark_success(pname, key)
            self._log_usage(model, pname, {}, time.time() - start, True)
        except Exception as e:
            if key:
                await self.key_manager.mark_failure(pname, key)
            self._log_usage(model, pname, {}, time.time() - start, False, str(e))
            raise

    def _log_usage(self, model, provider, usage, duration, success, error=""):
        entry = {"time": time.time(), "model": model, "provider": provider, "duration_ms": int(duration * 1000), "success": success, "error": error, "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)}
        self._usage_log.append(entry)
        if len(self._usage_log) > 10000:
            self._usage_log = self._usage_log[-5000:]

    def get_stats(self) -> dict:
        total = len(self._usage_log)
        ok = sum(1 for e in self._usage_log if e["success"])
        return {"total_requests": total, "success": ok, "failed": total - ok, "total_prompt_tokens": sum(e["prompt_tokens"] for e in self._usage_log), "total_completion_tokens": sum(e["completion_tokens"] for e in self._usage_log), "recent": self._usage_log[-20:]}

    def list_models(self) -> list[dict]:
        return [{"id": m, "owned_by": n} for n, p in self.providers.items() for m in p.models]


relay = Relay()
