"""模型接口层：发送 HTTP、解析本次消息与用量，不操作会话或数据库。"""
import httpx

from app.config import AppError


def complete(client: httpx.Client, api_key: str, payload: dict) -> tuple[dict, dict]:
    try:
        response = client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"}, json=payload,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise AppError(f"模型接口失败（HTTP {exc.response.status_code}），本次已停止。", code="model_http_error") from None
    except httpx.TimeoutException:
        raise AppError("模型请求超时，本次已停止，未自动重试。", code="model_timeout") from None
    except httpx.RequestError:
        raise AppError("模型网络请求失败，本次已停止，未自动重试。", code="model_network_error") from None
    try:
        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError
        counts = {name: data["usage"][name] for name in ("prompt_tokens", "completion_tokens", "total_tokens")}
        if not all(type(value) is int and value >= 0 for value in counts.values()):
            raise ValueError
        if choice["finish_reason"] == "length":
            raise AppError("模型输出被截断，请缩小问题范围后重试。", code="output_truncated", diagnostics={"usage": counts})
        return message, counts
    except (ValueError, KeyError, IndexError, TypeError):
        raise AppError("模型响应格式异常，本次已停止。", code="invalid_response") from None
