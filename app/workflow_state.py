"""第十五课：包装核对这一次执行的数据，不是聊天会话或数据库表。"""
from time import perf_counter
from typing import TypedDict


class PackageCheckState(TypedDict):
    sku: str
    started: float
    rules: dict | None
    detail: dict | None
    tool_trace: list[dict]
    model_trace: list[dict]
    node_trace: list[str]
    usage: dict[str, int]
    usage_complete: bool
    answer: str
    answer_details: dict | None
    outcome: str


def new_package_state(sku: str) -> PackageCheckState:
    # 每次请求独立创建；不把Key、HTTP客户端或数据库连接放进State。
    return {
        "sku": sku, "started": perf_counter(), "rules": None, "detail": None,
        "tool_trace": [], "model_trace": [], "node_trace": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "usage_complete": True, "answer": "", "answer_details": None, "outcome": "pending",
    }
