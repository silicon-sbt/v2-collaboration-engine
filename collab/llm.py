"""Minimal self-contained LLM client for the V2 engine (no upstream deps).

Consumes OpenAI-compatible chat-completions endpoints so any provider
(DeepSeek / OpenAI / OpenRouter / Gemini / custom base_url) works by setting
the corresponding environment key. MockLLM is deterministic and free, used
by tests and no-key demos. `last_usage` is refreshed on every generate so
the V2 audit reads objective token counts (never the agent self-report).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests


class LLMClient(Protocol):
    """Minimal object contract consumed by V2 nodes."""
    provider_name: str
    model: str

    def generate(self, prompt: str) -> str: ...


class MockLLM:
    """Deterministic local LLM for tests and no-key demos (free)."""

    def __init__(self, model: str = "mock") -> None:
        self.provider_name = "mock"
        self.model = model
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def generate(self, prompt: str) -> str:
        return "（mock）已生成。这是确定性占位输出，不代表真实模型判断。"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    api_key_envs: tuple[str, ...]
    default_model: str


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek", base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key_envs=("DEEPSEEK_API_KEY",), default_model="deepseek-chat",
    ),
    "openai": ProviderSpec(
        name="openai", base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key_envs=("OPENAI_API_KEY",), default_model="gpt-4o-mini",
    ),
    "openrouter": ProviderSpec(
        name="openrouter", base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key_envs=("OPENROUTER_API_KEY_1", "OPENROUTER_API_KEY_2"), default_model="openai/gpt-4o-mini",
    ),
    "gemini": ProviderSpec(
        name="gemini", base_url=os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
        api_key_envs=("GEMINI_API_KEY_1", "GEMINI_API_KEY_2"), default_model="gemini-2.0-flash",
    ),
}

AUTO_ORDER = ("deepseek", "openai", "openrouter", "gemini")

_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_ENV_LOADED: set[Path] = set()


def load_env_files(root_dir: Path | str | None) -> None:
    """Load a .env file into the process environment (idempotent)."""
    if root_dir is None:
        return
    path = (Path(root_dir) / ".env").resolve()
    if path in _ENV_LOADED or not path.exists():
        return
    _ENV_LOADED.add(path)
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'") :
            value = value[1:-1]
        if value and key not in os.environ:
            os.environ[key] = value


class OpenAICompatLLM:
    """OpenAI-compatible chat client satisfying the LLMClient protocol."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        provider_name: str = "openai-compatible",
        temperature: float = 0.7,
        max_output_tokens: int = 4096,
        timeout: float = 180.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def generate(self, prompt: str) -> str:
        url = self.base_url + "/chat/completions"
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        attempts = 0
        while True:
            attempts += 1
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempts >= self.max_retries:
                    raise RuntimeError("LLM request to " + url + " failed: " + str(exc)) from exc
                continue
            if response.status_code != 200:
                if attempts < self.max_retries and response.status_code in (429, 500, 502, 503, 504):
                    continue
                raise RuntimeError("LLM API error %s from %s: %s" % (response.status_code, self.provider_name, response.text[:300]))
            try:
                data = response.json()
                usage = data.get("usage") or {}
                self.last_usage = {
                    "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                    "completion_tokens": int(usage.get("completion_tokens", 0)),
                    "total_tokens": int(usage.get("total_tokens", 0)),
                }
                return str(data["choices"][0]["message"]["content"]).strip()
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError("Unexpected LLM API response from %s: %s" % (self.provider_name, response.text[:300])) from exc


def _first_key(spec: ProviderSpec) -> str | None:
    for env_name in spec.api_key_envs:
        value = os.getenv(env_name, "").strip()
        if value:
            return value
    return None


def resolve_llm(
    provider: str = "auto",
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.7,
    max_output_tokens: int = 4096,
    root_dir: Path | str | None = None,
) -> LLMClient:
    """Build an LLM client; mock and no-key auto fall back to MockLLM."""
    if root_dir is not None:
        load_env_files(root_dir)
    selected = (provider or "auto").strip().lower()
    if selected == "mock":
        return MockLLM(model=model or "mock")
    if selected == "auto":
        for name in AUTO_ORDER:
            spec = PROVIDER_SPECS[name]
            key = api_key or _first_key(spec)
            if key:
                return OpenAICompatLLM(
                    api_key=key, base_url=base_url or spec.base_url, model=model or spec.default_model,
                    provider_name=name, temperature=temperature, max_output_tokens=max_output_tokens,
                )
        return MockLLM(model="mock")
    spec = PROVIDER_SPECS.get(selected)
    if spec is not None:
        key = api_key or _first_key(spec)
        if not key:
            raise ValueError("Provider " + repr(selected) + " needs a key. Set " + "/".join(spec.api_key_envs) + " in .env or pass api_key.")
        return OpenAICompatLLM(
            api_key=key, base_url=base_url or spec.base_url, model=model or spec.default_model,
            provider_name=selected, temperature=temperature, max_output_tokens=max_output_tokens,
        )
    raise ValueError("Unknown provider: " + repr(selected))


__all__ = ["LLMClient", "MockLLM", "OpenAICompatLLM", "resolve_llm", "load_env_files"]