import uuid
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional


class BaseProvider(ABC):
    name: str = "base"

    def __init__(self, base_url: str, api_keys: List[str], models: Dict[str, str]):
        self.base_url = base_url.rstrip("/")
        self.api_keys = api_keys
        self.models = models

    @abstractmethod
    async def chat(self, model: str, messages: list, **kwargs) -> dict:
        ...

    @abstractmethod
    async def chat_stream(self, model: str, messages: list, **kwargs) -> AsyncIterator[dict]:
        ...

    @staticmethod
    def _normalize(name: str) -> str:
        return name.lower().replace("-", "").replace("_", "").replace(".", "")

    def resolve_model(self, model: str) -> str:
        if model in self.models:
            return self.models[model]
        # Fuzzy fallback: ignore case, hyphens, underscores, dots
        norm = self._normalize(model)
        for k, v in self.models.items():
            if self._normalize(k) == norm:
                return v
        return model

    def make_chunk(self, delta: dict, model: str, finish_reason: Optional[str] = None) -> dict:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
