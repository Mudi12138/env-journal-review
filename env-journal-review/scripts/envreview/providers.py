"""Model providers for API mode: mainstream presets plus any OpenAI-compatible endpoint.

Every provider is reached through the `openai` SDK, since all of them offer an
OpenAI-compatible chat endpoint. A preset fills in the base URL and the usual key variable;
`custom` takes both from ENVREVIEW_API_BASE_URL and ENVREVIEW_API_KEY. The standard
OPENAI_BASE_URL is never read, so an existing OpenAI setup cannot be redirected by accident.

Structured answers: OpenAI enforces the JSON schema server-side ("schema"); the others get
JSON mode ("object") or nothing ("none") plus the schema in the prompt, and the answer is
checked against the schema by the editor engine (a mismatch goes through its repair loop).
If an endpoint rejects `response_format` or `max_tokens`, the call is retried without it.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# name: base_url, key variables (first found wins), json mode, reasoning_effort supported,
# max_tokens to send (None = provider default), default model (None = --model required)
PRESETS: dict[str, dict[str, Any]] = {
    "openai": {"base_url": None, "key_env": ("OPENAI_API_KEY", "OPENAI_API_KEY_default"),
               "json": "schema", "reasoning_effort": True, "max_tokens": None,
               "model": "gpt-5.6-sol", "label": "OpenAI"},
    "claude": {"base_url": "https://api.anthropic.com/v1/", "key_env": ("ANTHROPIC_API_KEY",),
               "json": "none", "reasoning_effort": False, "max_tokens": 16384,
               "model": "claude-sonnet-5-5", "label": "Anthropic Claude"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "json": "object",
               "reasoning_effort": False, "max_tokens": None, "model": None, "label": "Google Gemini"},
    "deepseek": {"base_url": "https://api.deepseek.com", "key_env": ("DEEPSEEK_API_KEY",),
                 "json": "object", "reasoning_effort": False, "max_tokens": 32768,
                 "model": "deepseek-v4-pro", "label": "DeepSeek"},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "key_env": ("DASHSCOPE_API_KEY",), "json": "object", "reasoning_effort": False,
             "max_tokens": None, "model": None, "label": "Alibaba Qwen (DashScope)"},
    "doubao": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "key_env": ("ARK_API_KEY",),
               "json": "object", "reasoning_effort": False, "max_tokens": 16384, "model": None,
               "label": "ByteDance Doubao (Volcano Ark)"},
    "kimi": {"base_url": "https://api.moonshot.cn/v1", "key_env": ("MOONSHOT_API_KEY",),
             "json": "object", "reasoning_effort": False, "max_tokens": 16384, "model": None,
             "label": "Moonshot Kimi"},
    "glm": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "key_env": ("ZHIPUAI_API_KEY",),
            "json": "object", "reasoning_effort": False, "max_tokens": None, "model": None,
            "label": "Zhipu GLM"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": ("OPENROUTER_API_KEY",),
                   "json": "object", "reasoning_effort": False, "max_tokens": None, "model": None,
                   "label": "OpenRouter (many models)"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": (), "json": "object",
               "reasoning_effort": False, "max_tokens": None, "model": None,
               "label": "Ollama (local, free)"},
    "custom": {"base_url": None, "key_env": ("ENVREVIEW_API_KEY",), "json": "object",
               "reasoning_effort": False, "max_tokens": None, "model": None,
               "label": "Any OpenAI-compatible endpoint (ENVREVIEW_API_BASE_URL)"},
}

# model-name prefixes that identify a provider when --provider is not given
PREFIXES = [("gpt-", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
            ("claude", "claude"), ("gemini", "gemini"), ("deepseek", "deepseek"),
            ("qwen", "qwen"), ("doubao", "doubao"), ("kimi", "kimi"), ("moonshot", "kimi"),
            ("glm", "glm")]


def resolve(provider: str | None, model: str | None) -> tuple[str, str]:
    """(provider, model) from what the user gave; raises SystemExit with a clear message."""
    if provider and provider not in PRESETS:
        raise SystemExit(f"Unknown provider {provider!r}. Choose one of: {', '.join(PRESETS)}")
    if not provider:
        m = (model or "").lower()
        provider = next((p for pre, p in PREFIXES if m.startswith(pre)), None)
        if provider is None:
            provider = "custom" if os.environ.get("ENVREVIEW_API_BASE_URL") else "openai"
    model = model or PRESETS[provider]["model"]
    if not model:
        raise SystemExit(f"--model is required for {PRESETS[provider]['label']}: use a model id "
                         "from that provider's model list.")
    return provider, model


def base_url(provider: str) -> str | None:
    if provider == "custom":
        url = os.environ.get("ENVREVIEW_API_BASE_URL")
        if not url:
            raise SystemExit("Set ENVREVIEW_API_BASE_URL (the API root, e.g. https://host/v1) "
                             "and ENVREVIEW_API_KEY for the custom provider.")
        return url
    return os.environ.get(f"ENVREVIEW_{provider.upper()}_BASE_URL") or PRESETS[provider]["base_url"]


def api_key(provider: str) -> str | None:
    spec = PRESETS[provider]
    if not spec["key_env"]:
        return "ollama"                        # local server; any non-empty key is accepted
    return next((os.environ[k] for k in spec["key_env"] if os.environ.get(k)), None)


def key_status(provider: str) -> str:
    spec = PRESETS[provider]
    if not spec["key_env"]:
        return "no key needed"
    found = [k for k in spec["key_env"] if os.environ.get(k)]
    return f"key found in {found[0]}" if found else f"set {' or '.join(spec['key_env'])}"


class _Completions:
    """chat.completions with the provider's defaults and tolerant retries."""

    def __init__(self, inner, provider, max_tokens):
        self.inner, self.provider, self.max_tokens = inner, provider, max_tokens

    def create(self, **kw):
        import openai

        spec = PRESETS[self.provider]
        kw = dict(kw)
        if self.max_tokens and "max_tokens" not in kw:
            kw["max_tokens"] = self.max_tokens
        if spec["json"] == "none":
            kw.pop("response_format", None)
        for _ in range(3):
            try:
                return self.inner.create(**kw)
            except openai.BadRequestError as exc:
                msg = str(exc).lower()
                if "response_format" in msg and "response_format" in kw:
                    kw.pop("response_format")
                    continue
                if "max_tokens" in msg and "max_tokens" in kw:
                    kw.pop("max_tokens")
                    continue
                raise
        return self.inner.create(**kw)


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class Client:
    """An OpenAI client whose chat.completions applies the provider's quirks."""

    def __init__(self, provider: str, max_tokens: int | None = None):
        from openai import OpenAI

        key = api_key(provider)
        if not key:
            raise SystemExit(f"No API key for {PRESETS[provider]['label']}: {key_status(provider)}.")
        kwargs: dict[str, Any] = {"api_key": key, "timeout": 900, "max_retries": 3}
        url = base_url(provider)
        if url:
            kwargs["base_url"] = url
        self.raw = OpenAI(**kwargs)
        self.chat = _Chat(_Completions(self.raw.chat.completions, provider,
                                       max_tokens or PRESETS[provider]["max_tokens"]))


def loads_json(text: str) -> Any:
    """JSON from a model answer that may wrap it in ```json fences or a sentence."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            return json.loads(t[i:j + 1])
        raise


def install(E, max_tokens: int | None = None) -> None:
    """Make the editor engine (editor_v3) use these presets and clients."""
    for name, spec in PRESETS.items():
        E.PROVIDERS[name] = {"base_url": spec["base_url"], "key_env": spec["key_env"],
                             "json_schema": spec["json"] == "schema",
                             "reasoning_effort": spec["reasoning_effort"],
                             "max_tokens": None}      # sent by the client wrapper instead
    E.make_client = lambda provider: Client(provider, max_tokens)
    E.loads_json = loads_json
