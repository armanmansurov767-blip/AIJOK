"""Проверка настоящего запроса к Anthropic API без сети: SDK работает через подменённый транспорт."""
import json

import anthropic
import httpx2
import pytest

from app import llm
from app.config import Settings
from conftest import GOOD


def _client_with(handler):
    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return anthropic.Anthropic(api_key="test-key", http_client=http, max_retries=0)


def _message(text, stop="end_turn"):
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, ai_enabled=True)


def test_request_shape_and_parsing(settings, monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=_message(json.dumps(GOOD, ensure_ascii=False)))

    monkeypatch.setattr(llm, "make_client", lambda s: _client_with(handler))
    doc = llm.InputDoc(name="z.txt", kind="text", mime="text/plain", data=b"", text="Заявление")
    out = llm.read_documents(settings, [doc], "")
    assert out["type"] == GOOD["type"]

    body = seen["body"]
    assert seen["url"].endswith("/v1/messages?beta=true") or seen["url"].endswith("/v1/messages")
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"].get("anthropic-beta", "")
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "medium"
    assert "thinking" not in body and "temperature" not in body
    assert body["system"] == llm.SYSTEM
    assert body["messages"][0]["content"][0]["text"].startswith('<document name="z.txt">')


@pytest.mark.parametrize("status,needle", [
    (401, "Ключ Anthropic API"), (404, "не найдена"), (429, "Слишком много"), (500, "Ошибка сервиса"), (400, "не приняла"),
])
def test_api_errors_become_reader_errors(settings, monkeypatch, status, needle):
    def handler(request):
        return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "boom"}})

    monkeypatch.setattr(llm, "make_client", lambda s: _client_with(handler))
    with pytest.raises(llm.ReaderError) as e:
        llm.read_documents(settings, [], "Текст заявления для проверки")
    assert needle in str(e.value)


@pytest.mark.parametrize("stop,needle", [("refusal", "отказалась"), ("max_tokens", "оборвался")])
def test_stop_reasons(settings, monkeypatch, stop, needle):
    monkeypatch.setattr(llm, "make_client", lambda s: _client_with(lambda r: httpx2.Response(200, json=_message("{}", stop))))
    with pytest.raises(llm.ReaderError) as e:
        llm.read_documents(settings, [], "Текст заявления для проверки")
    assert needle in str(e.value)


def test_bad_json(settings, monkeypatch):
    monkeypatch.setattr(llm, "make_client", lambda s: _client_with(lambda r: httpx2.Response(200, json=_message("не json"))))
    with pytest.raises(llm.ReaderError):
        llm.read_documents(settings, [], "Текст заявления для проверки")
