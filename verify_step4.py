"""每轮在独立Python进程中运行FastAPI，验证不依赖进程内记忆；真实模型调用会计费。"""
import json
import os
from pathlib import Path
import subprocess
import sys

from app.session_repository import load_session


def fresh_process_request(body: dict) -> dict:
    # 子进程只经stdin收取练习问题，不输出Key或原始异常。
    source = """
import json,sys
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    response=client.post('/chat',json=json.load(sys.stdin))
    if response.status_code!=200:
        print(json.dumps({'verification_error':response.status_code}))
        sys.exit(1)
    print(json.dumps(response.json(),ensure_ascii=False))
"""
    child = subprocess.run(
        [sys.executable, "-c", source], input=json.dumps(body, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8", cwd=Path(__file__).resolve().parent,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=240,
    )
    if child.returncode != 0:
        raise RuntimeError("新进程中的/chat请求失败，未输出原始错误。")
    return json.loads(child.stdout)


def verify():
    first = fresh_process_request({"message": "找黑色0.5mm签字笔，单价不超过5元，请查询。"})
    session_id = first["session_id"]
    assert first["tool_trace"], "首轮没有执行工具"
    before = load_session(session_id)
    assert len(before["history"]) == 2
    second = fresh_process_request({"message": "换得力，其他不变", "session_id": session_id})
    assert second["session_id"] == session_id
    assert second["tool_trace"] and second["tool_trace"][0]["changes"] == {"brand": "得力"}
    for name in ("category", "color", "spec", "max_price_fen", "limit"):
        assert second["current_requirements"][name] == first["current_requirements"][name], f"条件丢失：{name}"
    products = second["tool_trace"][-1]["products"]
    assert products and all(p["brand"] == "得力" and p["color"] == "黑色" and p["spec"] == "0.5mm" and p["price_fen"] <= 500 for p in products)
    after = load_session(session_id)
    assert after["requirements"] == second["current_requirements"]
    assert len(after["history"]) == 4
    assert [m["role"] for m in after["history"]] == ["user", "assistant", "user", "assistant"]

    independent = fresh_process_request({"message": "找晨光蓝色0.7mm签字笔，单价不超过4元。"})
    assert independent["session_id"] != session_id
    assert independent["current_requirements"]["brand"] == "晨光"
    assert load_session(session_id) == after, "独立会话修改了原会话"
    for label, result in (("首轮", first), ("重启新进程后续聊", second), ("独立会话", independent)):
        print(json.dumps({"round": label, "requirements": result["current_requirements"],
                          "usage": result["usage"], "model_calls": result["model_calls"],
                          "elapsed_seconds": result["elapsed_seconds"], "answer": result["answer"]}, ensure_ascii=False))
    print("第四步真实验收通过：跨进程恢复上下文、条件保留、消息持久化、会话隔离。")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except Exception:
        print("第四步真实验收失败，请检查数据库/模型配置及状态保留；未输出原始异常。")
        sys.exit(1)
