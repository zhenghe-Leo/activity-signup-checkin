"""测试用的假 AI 客户端：不访问网络，不需要密钥。"""
from app.ai.client import AiFailure


class FakeChatClient:
    """按顺序返回预设的回复或失败；没有预设时表现为「未配置密钥」。记录每次调用的提示词。"""

    model = "fake-model"

    def __init__(self):
        self.calls: list[dict] = []
        self._queue: list = []

    def reply(self, text: str) -> "FakeChatClient":
        self._queue.append(text)
        return self

    def fail(self, reason: str, raw_output: str | None = None) -> "FakeChatClient":
        self._queue.append(AiFailure(reason, raw_output))
        return self

    def complete_json(self, system: str, user: str, temperature: float) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        if not self._queue:
            raise AiFailure("NO_KEY")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
