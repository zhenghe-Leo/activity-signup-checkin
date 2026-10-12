"""DeepSeek 客户端与失败分类（T3.1、BR-26、NFR-08）。用 httpx.MockTransport 模拟接口，不访问网络。"""
import json

import httpx
import pytest
from pydantic import SecretStr

from app.ai.client import AiFailure, DeepSeekClient

FAKE_KEY = "sk-test-fake-key-not-real"


def make_client(settings, handler, key=FAKE_KEY):
    s = settings.model_copy(update={"deepseek_api_key": SecretStr(key)})
    return DeepSeekClient(s, transport=httpx.MockTransport(handler))


def ok_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_br26_no_key_fails_without_sending_request(settings):
    calls = []
    client = make_client(settings, lambda req: calls.append(req) or ok_response("{}"), key="")
    with pytest.raises(AiFailure) as exc:
        client.complete_json("s", "u", 0)
    assert exc.value.reason == "NO_KEY" and calls == []


def test_success_uses_json_mode_bearer_key_and_model(settings):
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers["Authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return ok_response('{"a": 1}')

    assert make_client(settings, handler).complete_json("系统", "用户", 0.3) == '{"a": 1}'
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    body = seen["body"]
    assert body["model"] == "deepseek-flash" and body["temperature"] == 0.3
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [{"role": "system", "content": "系统"}, {"role": "user", "content": "用户"}]


def _raise(exc_type):
    def handler(request):
        raise exc_type("boom", request=request)
    return handler


@pytest.mark.parametrize("handler, reason", [
    (_raise(httpx.ReadTimeout), "TIMEOUT"),
    (_raise(httpx.ConnectTimeout), "TIMEOUT"),
    (_raise(httpx.ConnectError), "CALL_FAILED"),
    (lambda req: httpx.Response(401, json={"error": "invalid key"}), "CALL_FAILED"),
    (lambda req: httpx.Response(429, json={"error": "rate limit"}), "CALL_FAILED"),
    (lambda req: httpx.Response(500, text="server error"), "CALL_FAILED"),
    (lambda req: httpx.Response(200, text="not json"), "INVALID_OUTPUT"),
    (lambda req: httpx.Response(200, json={"choices": []}), "INVALID_OUTPUT"),
])
def test_br26_failures_are_classified(settings, handler, reason):
    """BR-26 / AC-23：超时、调用失败（含 401/429/5xx）、输出不合法分别归类。"""
    with pytest.raises(AiFailure) as exc:
        make_client(settings, handler).complete_json("s", "u", 0)
    assert exc.value.reason == reason


def test_nfr08_failure_never_exposes_key(settings):
    """NFR-08：异常信息与保留的原始输出中都不含密钥。"""
    with pytest.raises(AiFailure) as exc:
        make_client(settings, lambda req: httpx.Response(200, text="oops")).complete_json("s", "u", 0)
    assert FAKE_KEY not in str(exc.value) and FAKE_KEY not in repr(exc.value)
    assert FAKE_KEY not in (exc.value.raw_output or "")
