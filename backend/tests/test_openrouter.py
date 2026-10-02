"""AI provider (PROJECT.md v1.49): OpenRouter default, Gemini second. Everything here uses fakes; nothing is sent."""
import httpx
import pytest

from app import ai_analysis, settings
from app.ai_analysis import AIError, extract_json, generate_json, provider_of
from test_ai_analysis import REAL_POST_JSON
from test_app_settings import DEFAULTS, put

NEMOTRON = "nvidia/nemotron-3-ultra-550b-a55b:free"
SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "or-test-key-not-real")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")


def test_json_is_found_in_fenced_and_chatty_replies():
    assert extract_json('{"a": "x"}') == {"a": "x"}
    assert extract_json('```json\n{"a": "x"}\n```') == {"a": "x"}
    assert extract_json('Sure! Here it is: {"a": "x"} Hope that helps.') == {"a": "x"}
    for bad in ("", "no json here", "[1, 2]", '{"a": '):
        with pytest.raises(ValueError):
            extract_json(bad)


def test_provider_follows_the_model_id():
    assert provider_of(NEMOTRON) == "openrouter" and provider_of("gemini-3.8-flash") == "gemini"


def test_openrouter_request_shape_and_parsing(keys, monkeypatch):
    seen = {}

    def fake(url, headers, payload):
        seen.update(url=url, headers=headers, payload=payload)
        return {"choices": [{"message": {"content": '```json\n{"a": "hello"}\n```'}}]}
    monkeypatch.setattr(ai_analysis, "post_json", fake)
    assert generate_json("SYS", {"q": 1}, SCHEMA, NEMOTRON, 0.3) == {"a": "hello"}
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer or-test-key-not-real"
    p = seen["payload"]
    assert p["model"] == NEMOTRON and p["temperature"] == 0.3 and "response_format" not in p
    assert p["messages"][0]["role"] == "system" and p["messages"][0]["content"].startswith("SYS")
    assert '"properties"' in p["messages"][0]["content"]  # the schema travels in the prompt
    assert p["messages"][1] == {"role": "user", "content": '{"q": 1}'}


@pytest.mark.parametrize("data", [{"choices": [{"message": {"content": None}}]}, {"choices": []}, {},
                                  {"choices": [{"message": {"content": "I cannot help"}}]}])
def test_unusable_replies_are_errors_not_crashes(keys, monkeypatch, data):
    monkeypatch.setattr(ai_analysis, "post_json", lambda *a: data)
    with pytest.raises(AIError, match="OpenRouter returned no usable JSON"):
        generate_json("SYS", {}, SCHEMA, NEMOTRON)


def test_no_key_means_error_and_no_request(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    with pytest.raises(AIError, match="OPENROUTER_API_KEY is not set"):
        generate_json("SYS", {}, SCHEMA, NEMOTRON)


class Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body or {}

    def json(self):
        return self._body


@pytest.mark.parametrize("code,match", [(429, "rate limited by OpenRouter"), (502, "OpenRouter is busy"),
                                        (503, "OpenRouter is busy"), (401, "OpenRouter returned HTTP 401: bad key")])
def test_http_errors_are_named_after_the_provider(monkeypatch, code, match):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: Resp(code, {"error": {"message": "bad key"}}))
    with pytest.raises(AIError, match=match):
        REAL_POST_JSON("https://openrouter.ai/api/v1/chat/completions", {}, {})


def test_provider_is_automatic_then_chosen(client, keys, monkeypatch):
    assert client.get("/ai/status").json()["provider"] == "openrouter"
    assert client.get("/ai/status").json()["model"] == settings.OPENROUTER_MODEL
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g-test-key-not-real")
    monkeypatch.setattr(ai_analysis, "list_models", lambda provider="gemini": ["gemini-x-flash"])
    assert put(client, ai_provider="gemini").status_code == 200
    s = client.get("/ai/status").json()
    assert s["provider"] == "gemini" and s["model"] == settings.GEMINI_MODEL
    assert client.get("/settings").json()["ai_keys"] == {"openrouter": True, "gemini": True}


def test_settings_refuse_a_provider_without_key_and_a_model_of_the_wrong_provider(client, keys, monkeypatch):
    assert put(client, ai_provider="gemini").status_code == 409                       # no Gemini key
    r = put(client, ai_model="gemini-x-flash")                                        # Gemini name while OpenRouter is active
    assert r.status_code == 422 and "not a openrouter model" in r.json()["detail"]
    monkeypatch.setattr(ai_analysis, "list_models", lambda provider="gemini": [NEMOTRON, "vendor/other"])
    assert client.get("/settings/ai-models").json() == {"provider": "openrouter", "models": sorted([NEMOTRON, "vendor/other"])}
    assert put(client, ai_model="vendor/nope").status_code == 422
    assert put(client, ai_model="vendor/other").status_code == 200
    assert client.get("/ai/status").json()["model"] == "vendor/other"


def test_a_stale_model_of_the_other_provider_is_ignored(client, keys, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g-test-key-not-real")
    monkeypatch.setattr(ai_analysis, "list_models", lambda provider="gemini": ["gemini-x-flash", "vendor/other"])
    put(client, ai_provider="gemini", ai_model="gemini-x-flash")
    assert client.get("/ai/status").json()["model"] == "gemini-x-flash"
    put(client, ai_provider="openrouter", ai_model=None)
    assert client.get("/ai/status").json()["model"] == settings.OPENROUTER_MODEL


def test_the_openrouter_key_never_reaches_a_log_line(monkeypatch):
    from app import security
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-v1-FAKEFAKEFAKEFAKE1234")
    assert "sk-or-v1-FAKE" not in security.redact("calling with sk-or-v1-FAKEFAKEFAKEFAKE1234 now")
