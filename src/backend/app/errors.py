"""业务异常与错误码表（03 §5.6）。

业务代码只抛 AppError(code)；HTTP 状态和默认中文提示从 ERROR_TABLE 查。
统一响应结构：{"code": ..., "message": ..., "details": ...可选}（NFR-05）。
"""
from typing import Any

# code -> (HTTP 状态, 默认中文提示)
ERROR_TABLE: dict[str, tuple[int, str]] = {
    "VALIDATION_ERROR": (422, "请求参数不合法"),
    "UNAUTHENTICATED": (401, "请先选择身份"),
    "FORBIDDEN": (403, "无权限"),
    "NOT_FOUND": (404, "资源不存在"),
    "METHOD_NOT_ALLOWED": (405, "请求方法不被允许"),
    "ACTIVITY_NOT_FOUND": (404, "活动不存在"),
    "FIELD_INVALID": (400, "字段不合法"),
    "CONTENT_INVALID": (400, "内容校验未通过"),
    "CHECKIN_CODE_INVALID": (400, "签到口令错误"),
    "ALREADY_REGISTERED": (409, "您已报名该活动"),
    "ALREADY_WAITLISTED": (409, "您已在候补队列中"),
    "REG_DEADLINE_PASSED": (409, "报名已截止"),
    "ACTIVITY_STARTED": (409, "活动已开始"),
    "ACTIVITY_CANCELLED": (409, "活动已取消"),
    "NOT_REGISTERED": (409, "您没有可取消的报名"),
    "CANCEL_AFTER_CHECKIN": (409, "已签到，不能取消报名"),
    "CHECKIN_NOT_OPEN": (409, "签到尚未开始"),
    "CHECKIN_CLOSED": (409, "签到已结束"),
    "CHECKIN_NOT_REGISTERED": (409, "您未报名该活动"),
    "CHECKIN_WAITLISTED": (409, "您在候补中，未获得名额，无法签到"),
    "ALREADY_CHECKED_IN": (409, "您已签到，请勿重复签到"),
    "ACTIVITY_NOT_EDITABLE": (409, "当前状态不允许此操作"),
    "USE_CHANGE_FLOW": (409, "已发布活动的名额、时间、地点、截止时间需通过「预览 → 确认」修改"),
    "CHANGE_LOCKED": (409, "签到已开放，活动不可再调整或取消"),
    "PREVIEW_STALE": (409, "报名数据已变化，请重新预览"),
    "SYSTEM_BUSY": (503, "系统繁忙，请稍后重试"),
    "INTERNAL_ERROR": (500, "服务器内部错误"),
}


class AppError(Exception):
    def __init__(self, code: str, message: str | None = None, details: Any = None):
        if code not in ERROR_TABLE:
            raise ValueError(f"未登记的错误码：{code}")
        self.code = code
        self.status_code, default_message = ERROR_TABLE[code]
        self.message = message or default_message
        self.details = details
        super().__init__(f"{code}: {self.message}")

    def to_body(self) -> dict:
        return error_body(self.code, self.message, self.details)


def error_body(code: str, message: str, details: Any = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return body
