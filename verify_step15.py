"""第十五课：默认离线对照第14课基线；--with-live额外调用真实模型和MySQL。"""
import argparse
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.evaluation import write_report
from app.main import app
from app.schemas import GetProductDetailArgs
import app.workflows as current

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs" / "15-langgraph-evaluation.json"
BASELINE = "lesson-14-baseline"
RULE = "KB-PACK-001-C002"
SKU = "DEMO-PEN-0000"
PASSAGE = {"source_id": "KB-PACK-001", "chunk_id": RULE, "title": "包装规则",
           "content": "缺少具体数量不能猜。", "source": "knowledge/KB-PACK-001.md"}
COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
NODES = ["load_rules", "load_detail", "compose_answer"]


def load_reference():
    result = subprocess.run(["git", "show", f"{BASELINE}:app/workflows.py"], cwd=ROOT,
                            capture_output=True, encoding="utf-8")
    if result.returncode:
        raise AppError("找不到本地基线标签；请先取回lesson-14-baseline标签。", code="verification_failed")
    module = types.ModuleType("lesson14_workflow_reference")
    # 只加载自己仓库标签中的旧代码，用于验证；不执行模型提供的文本。
    exec(compile(result.stdout, f"{BASELINE}:app/workflows.py", "exec"), module.__dict__)
    return module


def comparable(value):
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items()
                if key not in {"elapsed_seconds", "node_trace", "workflow_engine"}}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return value


def fixture_run(module, case):
    product = {"sku": SKU, "package_notes": None if case == "missing_packaging" else "按支销售，未提供盒装数量。"}

    def rules(args):
        if case == "rules_failed":
            raise AppError("internal-canary")
        return [PASSAGE]

    def summary(client, key, payload):
        assert "tools" not in payload
        if case == "model_timeout":
            raise AppError("模拟超时", code="model_timeout")
        if case == "extra_tool":
            return {"tool_calls": [{"id": "extra"}]}, dict(COUNTS)
        return {"content": json.dumps({"claims": [{"text": "当前不能确认盒装数量。",
                "evidence_ids": [RULE, "SKU:" + SKU]}], "unknowns": ["实际一盒数量未知。"]})}, dict(COUNTS)

    with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "verification-placeholder", "DEEPSEEK_MODEL": "verification-model"}), \
            patch.object(module, "search_knowledge", side_effect=rules), \
            patch.object(module, "get_product_detail", return_value=None if case == "not_found" else product), \
            patch.object(module, "complete", side_effect=summary):
        try:
            return {"status": "ok", "result": module.run_package_check(GetProductDetailArgs(sku=SKU))}
        except AppError as exc:
            return {"status": "error", "code": exc.code, "message": str(exc), "diagnostics": exc.diagnostics}


def offline_comparison():
    reference = load_reference()
    rows = []
    for case in ("answered", "missing_packaging", "not_found", "rules_failed", "model_timeout", "extra_tool"):
        before, after = fixture_run(reference, case), fixture_run(current, case)
        assert comparable(before) == comparable(after), f"基线行为不一致：{case}"
        details = after["result"] if after["status"] == "ok" else after["diagnostics"]
        assert details["node_trace"] == (["load_rules"] if case == "rules_failed" else NODES)
        rows.append({"case": case, "matched_baseline": True, "baseline": before, "graph": after})
    return rows


def live_checks():
    rows = []
    with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "rerank"}), TestClient(app) as client:
        for sku in ("DEMO-PEN-0000", "DEMO-PEN-0001", "DEMO-NOT-EXIST-999"):
            response = client.post("/workflows/package-check", json={"sku": sku})
            if response.status_code != 200:
                raise AppError(f"真实图流程失败（HTTP {response.status_code}）。", code="verification_failed")
            result = response.json()
            assert result["workflow_engine"] == "langgraph" and result["node_trace"] == NODES
            assert result["execution_mode"] == "workflow" and result["current_requirements"] == {}
            assert [row["tool"] for row in result["tool_trace"]] == ["search_knowledge", "get_product_detail"]
            if sku == "DEMO-NOT-EXIST-999":
                assert result["outcome"] == "not_found" and result["model_calls"] == 0
                assert result["usage"]["total_tokens"] == 0
            else:
                assert result["outcome"] == "answered" and result["model_calls"] == 1
                assert result["answer_details"]["unknowns"]
                references = {ref for claim in result["answer_details"]["claims"] for ref in claim["evidence_ids"]}
                assert "SKU:" + sku in references and any(ref.startswith("KB-PACK-001-") for ref in references)
            rows.append({"sku": sku, **result})
            print(json.dumps({"sku": sku, "nodes": result["node_trace"], "model_calls": result["model_calls"],
                              "usage": result["usage"], "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False), flush=True)
        invalid = client.post("/workflows/package-check", json={"sku": "../../secret"})
        assert invalid.status_code == 422
    return rows


def verify(with_live=False):
    report = {
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "baseline_tag": BASELINE, "langgraph_version": version("langgraph"),
        "langchain_core_version": version("langchain-core"), "offline": [],
        "live_checks": {"status": "skipped", "reason": "未提供--with-live；未调用真实模型或MySQL。"},
        "passed": False,
    }
    try:
        report["offline"] = offline_comparison()
        print("6个离线场景与第14课标签中的原实现行为一致。", flush=True)
        if with_live:
            report["live_checks"] = {"status": "passed", "cases": live_checks()}
        report["passed"] = True
    except (AppError, AssertionError, OSError) as exc:
        report["error_code"] = exc.code if isinstance(exc, AppError) else "verification_failed"
        if with_live and report["offline"]:
            report["live_checks"] = {"status": "failed"}
        raise AppError("第15课验收未通过，已保存本次报告。", code="verification_failed") from None
    finally:
        write_report(OUTPUT, report)
    print("第15课验收通过；报告位于outputs/15-langgraph-evaluation.json。", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-live", action="store_true", help="额外验证真实DeepSeek与MySQL；API会计费")
    args = parser.parse_args()
    try:
        verify(with_live=args.with_live)
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
