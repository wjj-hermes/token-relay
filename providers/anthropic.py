import json
import uuid
import httpx
from typing import AsyncIterator
from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def _to_anthropic(self, model: str, messages: list, **kwargs) -> tuple[dict, dict]:
        system_parts = []
        msg_list = []
        for m in messages:
            role = m.get("role", "user")
            if role == "system":
                system_parts.append(m.get("content", ""))
            else:
                msg_list.append({"role": role, "content": self._extract_content(m.get("content", ""))})

        body = {"model": self.resolve_model(model), "max_tokens": kwargs.get("max_tokens", 4096), "messages": msg_list}
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if "temperature" in kwargs and kwargs["temperature"] is not None:
            body["temperature"] = kwargs["temperature"]
        if "tools" in kwargs and kwargs["tools"]:
            body["tools"] = self._convert_tools(kwargs["tools"])

        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        api_key = self._pick_key()
        if api_key:
            headers["x-api-key"] = api_key
        return body, headers

    def _to_openai_response(self, data: dict, model: str) -> dict:
        content = data.get("content", [])
        text_parts = []
        tool_calls = []
        for block in content:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                    "type": "function",
                    "function": {"name": block.get("name", ""), "arguments": json.dumps(block.get("input", {}), ensure_ascii=False)},
                })

        stop_map = {"end_turn": "stop", "max_tokens": "length", "tool_use": "tool_calls"}
        usage = data.get("usage", {})
        msg = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
        if tool_calls:
            msg["tool_calls"] = tool_calls

        return {
            "id": data.get("id", f"chatcmpl-{uuid.uuid4().hex[:24]}"),
            "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": stop_map.get(data.get("stop_reason", ""), "stop")}],
            "usage": {"prompt_tokens": usage.get("input_tokens", 0), "completion_tokens": usage.get("output_tokens", 0), "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)},
        }

    async def chat(self, model: str, messages: list, **kwargs) -> dict:
        body, headers = self._to_anthropic(model, messages, **kwargs)
        body["stream"] = False
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{self.base_url}/v1/messages", json=body, headers=headers)
            data = resp.json()
            if resp.status_code != 200:
                raise Exception(f"Anthropic error {resp.status_code}: {json.dumps(data, ensure_ascii=False)[:500]}")
            return self._to_openai_response(data, model)

    async def chat_stream(self, model: str, messages: list, **kwargs) -> AsyncIterator[dict]:
        body, headers = self._to_anthropic(model, messages, **kwargs)
        body["stream"] = True
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", f"{self.base_url}/v1/messages", json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    raise Exception(f"Anthropic error {resp.status_code}: {text.decode()[:500]}")
                tools_started = set()
                buf = ""
                async for chunk in resp.aiter_text():
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        etype = event.get("type", "")
                        if etype == "message_start":
                            yield self.make_chunk({"role": "assistant", "content": ""}, model)
                        elif etype == "content_block_start":
                            cb = event.get("content_block", {})
                            if cb.get("type") == "tool_use":
                                tools_started.add(event.get("index", 0))
                                yield self.make_chunk({"tool_calls": [{"index": len(tools_started) - 1, "id": cb.get("id", ""), "type": "function", "function": {"name": cb.get("name", ""), "arguments": ""}}]}, model)
                        elif etype == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta" and delta.get("text"):
                                yield self.make_chunk({"content": delta["text"]}, model)
                            elif delta.get("type") == "input_json_delta" and delta.get("partial_json"):
                                yield self.make_chunk({"tool_calls": [{"index": max(0, len(tools_started) - 1), "function": {"arguments": delta["partial_json"]}}]}, model)
                        elif etype == "message_delta":
                            stop_map = {"end_turn": "stop", "max_tokens": "length", "tool_use": "tool_calls"}
                            yield self.make_chunk({}, model, finish_reason=stop_map.get(event.get("delta", {}).get("stop_reason", ""), "stop"))

    def _extract_content(self, content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(p.get("text", "") if isinstance(p, dict) and p.get("type") == "text" else str(p) for p in content)
        return str(content)

    def _convert_tools(self, tools: list) -> list:
        return [{"name": t.get("function", {}).get("name", ""), "description": t.get("function", {}).get("description", ""), "input_schema": t.get("function", {}).get("parameters", {"type": "object", "properties": {}})} for t in tools if t.get("type") == "function"]

    def _pick_key(self) -> str:
        if not self.api_keys:
            return ""
        key = self.api_keys[0]
        self.api_keys.append(self.api_keys.pop(0))
        return key
