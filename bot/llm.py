"""DeepSeek API 客户端：OpenAI 兼容 Chat Completions，JSON 输出。
仅用标准库 urllib，零第三方依赖。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


class LLMClient:
    def __init__(self, cfg: dict[str, Any]):
        ds = cfg.get("deepseek", {})
        api_key_env = ds.get("api_key_env", "DEEPSEEK_API_KEY")
        self.api_key = (ds.get("api_key") or os.environ.get(api_key_env, "")).strip()
        self.base_url = (ds.get("base_url") or "https://api.deepseek.com").rstrip("/")
        self.model = ds.get("model", "deepseek-chat")
        self.temperature = float(ds.get("temperature", 0.1))
        self.timeout = float(ds.get("timeout_sec", 60))
        self.enabled = bool(self.api_key) and bool(cfg.get("use_llm", True))

    def chat_json(self, system: str, user: str, temperature: Optional[float] = None) -> Optional[dict]:
        """调用模型并要求输出 JSON 对象。失败返回 None（调用方自行降级）。"""
        if not self.enabled:
            return None
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return self._parse_json(content)
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as e:
            print(f"[llm] 调用失败(将降级规则解析): {e}")
            return None

    @staticmethod
    def _parse_json(content: str) -> Optional[dict]:
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
        try:
            obj = json.loads(content)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            # 尝试截取第一个 { ... 最后一个 }
            s, e = content.find("{"), content.rfind("}")
            if s >= 0 and e > s:
                try:
                    obj = json.loads(content[s : e + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
            return None
