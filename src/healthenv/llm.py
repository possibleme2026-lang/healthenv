"""Minimal OpenAI-compatible client used only during environment synthesis."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class OpenAICompatibleClient:
    base_url: str
    api_key: str
    model: str
    timeout: int = 120

    @classmethod
    def from_env(cls) -> OpenAICompatibleClient:
        base_url = os.getenv("TIERFLOW_BASE_URL", "https://tierflow.cn/v1").rstrip("/")
        api_key = os.getenv("TIERFLOW_API_KEY", "")
        model = os.getenv("TIERFLOW_MODEL", "tierflow_pro")
        if not api_key:
            raise LLMError("TIERFLOW_API_KEY is not set")
        return cls(base_url=base_url, api_key=api_key, model=model)

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise LLMError(f"OpenAI-compatible request failed: {error}") from error
        try:
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
            result = json.loads(content)
            if not isinstance(result, dict):
                raise TypeError("response content is not an object")
            return result
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise LLMError("model response did not contain a JSON object") from error
