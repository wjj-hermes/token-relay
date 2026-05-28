import json
import httpx
from typing import AsyncIterator
from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    name = "openai"

    async def chat(self, model: str, messages: list, **kwargs) -> dict:
        body = {"model": self.resolve_model(model), "messages": messages, "stream": False}
        for k in ("temperature", "max_tokens", "top_p", "tools", "tool_choice", "stop"):
            if k in kwargs and kwargs[k] is not None:
                body[k] = kwargs[k]

        headers = {"Content-Type": "application/json"}
        api_key = self._pick_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = httpx.Timeout(connect=30, read=300, write=30, pool=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            data = resp.json()
            if resp.status_code != 200:
                raise Exception(f"Upstream error {resp.status_code}: {json.dumps(data, ensure_ascii=False)[:500]}")
            return data

    async def chat_stream(self, model: str, messages: list, **kwargs) -> AsyncIterator[dict]:
        body = {"model": self.resolve_model(model), "messages": messages, "stream": True}
        for k in ("temperature", "max_tokens", "top_p", "tools", "tool_choice", "stop"):
            if k in kwargs and kwargs[k] is not None:
                body[k] = kwargs[k]

        headers = {"Content-Type": "application/json"}
        api_key = self._pick_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = httpx.Timeout(connect=30, read=300, write=30, pool=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{self.base_url}/chat/completions", json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    raise Exception(f"Upstream error {resp.status_code}: {text.decode()[:500]}")
                buf = ""
                async for chunk in resp.aiter_text():
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data: "):
                            continue
                        ds = line[6:]
                        if ds == "[DONE]":
                            return
                        try:
                            yield json.loads(ds)
                        except json.JSONDecodeError:
                            pass

    def _pick_key(self) -> str:
        if not self.api_keys:
            return ""
        key = self.api_keys[0]
        self.api_keys.append(self.api_keys.pop(0))
        return key
