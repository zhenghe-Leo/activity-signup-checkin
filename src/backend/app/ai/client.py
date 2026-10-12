"""DeepSeek 调用与失败分类（T3.1、BR-26、DEC-03）。

只负责「发请求、拿到模型返回的文本」，不理解业务含义。失败统一抛 AiFailure，原因只有 4 类；
调用方捕获后直接降级，不重试。密钥只出现在请求头里，不写入日志、异常信息或返回值。
"""
from typing import Protocol

import httpx

from app.config import Settings

# 降级原因 → 界面文案（03 §8.5）
REASON_TEXT = {
    "NO_KEY": "未配置 API 密钥",
    "TIMEOUT": "请求超时",
    "CALL_FAILED": "服务调用失败",
    "INVALID_OUTPUT": "输出格式不合法",
}


class AiFailure(Exception):
    def __init__(self, reason: str, raw_output: str | None = None):
        assert reason in REASON_TEXT, reason
        self.reason = reason
        self.raw_output = raw_output  # INVALID_OUTPUT 时保留模型原文，写入 AI 调用日志
        super().__init__(reason)


class ChatClient(Protocol):
    model: str | None

    def complete_json(self, system: str, user: str, temperature: float) -> str:
        """返回模型输出的文本（应为 JSON）；失败抛 AiFailure。"""
        ...


class DeepSeekClient:
    """OpenAI 兼容的 Chat Completions 接口，开启 JSON 输出模式。"""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._settings = settings
        self._transport = transport  # 测试中注入 httpx.MockTransport，不访问网络
        self.model = settings.deepseek_model

    def complete_json(self, system: str, user: str, temperature: float) -> str:
        key = self._settings.deepseek_api_key.get_secret_value().strip()
        if not key:
            raise AiFailure("NO_KEY")
        try:
            with httpx.Client(transport=self._transport, timeout=self._settings.ai_timeout_seconds) as http:
                resp = http.post(
                    self._settings.deepseek_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": self.model,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
        except httpx.TimeoutException:
            raise AiFailure("TIMEOUT") from None
        except httpx.HTTPError:
            raise AiFailure("CALL_FAILED") from None
        if resp.status_code != 200:  # 包括密钥无效 401、限流 429
            raise AiFailure("CALL_FAILED")
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise AiFailure("INVALID_OUTPUT", raw_output=resp.text[:4000]) from None
        if not isinstance(content, str):
            raise AiFailure("INVALID_OUTPUT", raw_output=str(content)[:4000])
        return content


def source(mode: str, reason: str | None, model: str | None) -> dict:
    """接口返回的 AiSource（03 §5.1）。"""
    return {"mode": mode, "reason": reason, "reason_text": REASON_TEXT.get(reason), "model": model}
