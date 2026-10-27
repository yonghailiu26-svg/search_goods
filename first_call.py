"""第一课：读取本地配置，完成一次真实、非流式的文本请求。"""

import json
import os
from pathlib import Path
import sys
from time import perf_counter

import httpx
from dotenv import load_dotenv


def main() -> int:
    # 用脚本所在目录定位配置，避免 VS Code 工作目录不同导致找不到文件。
    # 已有进程环境变量优先于 .env.dev。
    load_dotenv(Path(__file__).with_name(".env.dev"))
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "").strip()
    if not api_key or not model:
        print("请在本地 .env.dev 填写 DEEPSEEK_API_KEY 和 DEEPSEEK_MODEL。")
        return 1

    # messages 类似前端传给服务端的 JSON 消息数组。
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一位简洁的中文 Agent 学习助手。"},
            {"role": "user", "content": "请用两句话说明：大模型与 Agent 有什么关系？"},
        ],
        "stream": False,
        "thinking": {"type": "disabled"},
        "max_tokens": 256,
    }

    started = perf_counter()
    try:
        # 固定官方地址；密钥只用于 Authorization，不写入输出。
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        hints = {
            400: "请求参数不被接受，请核对模型名及官方参数说明。",
            401: "鉴权失败，请在本地检查 Key。",
            402: "余额不足，请检查官方账户余额。",
            429: "触发限流，请稍后再试。",
        }
        print(f"调用失败：HTTP {status}。{hints.get(status, '请检查服务状态及模型配置。')}")
        return 1
    except httpx.RequestError:
        print("网络请求失败或超时，请检查网络后再运行。")
        return 1

    try:
        data = response.json()
        answer = data["choices"][0]["message"]["content"]
        usage = data["usage"]
        # 只选取需要的计数，不打印完整响应或原始错误正文。
        token_counts = {
            name: usage[name]
            for name in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty answer")
        if not all(type(value) is int and value >= 0 for value in token_counts.values()):
            raise ValueError("invalid usage")
    except (ValueError, KeyError, IndexError, TypeError):
        print("响应缺少有效的文本回答或 usage，未通过本课验收。")
        return 1

    print("模型回答：")
    print(answer.replace(api_key, "[REDACTED]"))
    print("usage：", json.dumps(token_counts, ensure_ascii=False))
    print(f"耗时：{perf_counter() - started:.2f} 秒")
    return 0


if __name__ == "__main__":
    # Windows 终端和 VS Code 输出统一使用 UTF-8，避免中文乱码。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
