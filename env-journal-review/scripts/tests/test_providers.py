"""Provider presets: resolving provider/model, tolerant JSON, and retries without rejected params."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx
import openai

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from envreview import providers as P  # noqa: E402


def bad_request(msg):
    req = httpx.Request("POST", "http://x/chat/completions")
    return openai.BadRequestError(msg, response=httpx.Response(400, request=req), body=None)


class FakeInner:
    def __init__(self, reject=()):
        self.reject, self.calls = list(reject), []

    def create(self, **kw):
        self.calls.append(dict(kw))
        for word in self.reject:
            if word in kw:
                raise bad_request(f"Unsupported parameter: {word}")
        return "ok"


class Providers(unittest.TestCase):
    def test_resolve(self):
        self.assertEqual(P.resolve(None, "deepseek-v4-pro"), ("deepseek", "deepseek-v4-pro"))
        self.assertEqual(P.resolve(None, "claude-sonnet-5-5")[0], "claude")
        self.assertEqual(P.resolve("deepseek", None), ("deepseek", "deepseek-v4-pro"))
        with self.assertRaises(SystemExit):
            P.resolve("qwen", None)                       # no default model
        with self.assertRaises(SystemExit):
            P.resolve("nope", "m")
        with mock.patch.dict(os.environ, {"ENVREVIEW_API_BASE_URL": "http://h/v1"}):
            self.assertEqual(P.resolve(None, "my-local-model")[0], "custom")

    def test_standard_openai_base_url_is_ignored(self):
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": "http://elsewhere/v1"}):
            self.assertIsNone(P.base_url("openai"))

    def test_loads_json(self):
        self.assertEqual(P.loads_json('```json\n{"ok": true}\n```'), {"ok": True})
        self.assertEqual(P.loads_json('Here it is: {"a": 1} hope that helps'), {"a": 1})

    def test_retries_without_rejected_parameters(self):
        inner = FakeInner(reject=("response_format", "max_tokens"))
        c = P._Completions(inner, "kimi", 16384)
        self.assertEqual(c.create(model="m", messages=[], response_format={"type": "json_object"}), "ok")
        self.assertNotIn("response_format", inner.calls[-1])
        self.assertNotIn("max_tokens", inner.calls[-1])
        self.assertEqual(inner.calls[0]["max_tokens"], 16384)

    def test_json_mode_none_drops_response_format(self):
        inner = FakeInner()
        P._Completions(inner, "claude", None).create(model="m", messages=[],
                                                     response_format={"type": "json_object"})
        self.assertNotIn("response_format", inner.calls[0])

    def test_other_errors_are_not_swallowed(self):
        inner = FakeInner(reject=("temperature",))
        with self.assertRaises(openai.BadRequestError):
            P._Completions(inner, "glm", None).create(model="m", messages=[], temperature=0)


if __name__ == "__main__":
    unittest.main()
