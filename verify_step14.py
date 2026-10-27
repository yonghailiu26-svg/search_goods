"""一次运行单元测试、四策略本地评测、基线回归；--with-agent会调用计费API。"""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from importlib.metadata import version
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch

from app.config import AppError, integer
from app.embeddings import RECIPE, model_name
from app.hybrid_search import RRF_K
from app.evaluation import aggregate_scores, load_cases, quality_checks, score_case, write_report
from app.knowledge import search_knowledge
from app.knowledge_index import PROJECT_ROOT, load_index
from app.reranking import reranker_name
from app.schemas import SearchKnowledgeArgs
from app.vector_index import corpus_hash, minimum_score

DATASET = PROJECT_ROOT / "evals" / "retrieval_cases.json"
REPORT = PROJECT_ROOT / "outputs" / "14-regression-report.json"
BASELINE = PROJECT_ROOT / "outputs" / "14-retrieval-baseline.json"


def verify(*, with_agent=False, update_baseline=False):
    started = perf_counter()
    print("阶段1/3：运行所有行为测试。", flush=True)
    unit = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=PROJECT_ROOT, timeout=180)
    report = {"created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(), "unit_tests_passed": unit.returncode == 0,
              "live_requested": with_agent, "strategies": {}, "errors": []}
    if unit.returncode != 0:
        report["passed"] = False
        write_report(REPORT, report)
        raise AppError("行为测试未通过，已停止后续评测并保存报告。", code="evaluation_failed")
    corpus = load_index()
    available = {chunk.chunk_id for chunk in corpus.chunks}
    dataset = load_cases(DATASET, available)
    metadata = {"dataset_hash": sha256(DATASET.read_bytes()).hexdigest(), "corpus_hash": corpus_hash(corpus),
                "embedding_model": model_name(), "reranker_model": reranker_name(), "semantic_min_score": minimum_score(),
                "candidate_limit": integer("KNOWLEDGE_CANDIDATE_LIMIT", 10, 3, 50), "k": 3,
                "embedding_recipe": RECIPE, "rrf_k": RRF_K, "fastembed_version": version("fastembed")}
    report.update(metadata=metadata, python_version=platform.python_version())
    print("阶段2/3：四种检索策略，各运行固定的8条样例。", flush=True)
    for strategy in ("keyword", "semantic", "hybrid", "rerank"):
        rows, metrics = [], []
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": strategy}):
            for case in dataset.cases:
                case_started = perf_counter()
                try:
                    passages = search_knowledge(SearchKnowledgeArgs(query=case.query, limit=3))
                    ids = [p["chunk_id"] for p in passages]
                    if set(ids) - available:
                        raise ValueError
                    score = score_case(ids, case.relevant_chunk_ids)
                    metrics.append(score)
                    rows.append({"id": case.id, "query": case.query, "expected_ids": case.relevant_chunk_ids,
                                 "retrieved_ids": ids, "metrics": score, "elapsed_seconds": round(perf_counter() - case_started, 4)})
                except (AppError, ValueError) as exc:
                    report["errors"].append({"strategy": strategy, "case": case.id, "code": exc.code if isinstance(exc, AppError) else "invalid_evaluation_data"})
        summary = aggregate_scores(metrics)
        report["strategies"][strategy] = {"summary": summary, "cases": rows}
        print(json.dumps({"strategy": strategy, **summary}, ensure_ascii=False), flush=True)
    baseline, compatible = None, True
    if BASELINE.exists() and not update_baseline:
        saved = json.loads(BASELINE.read_text(encoding="utf-8"))
        compatible = saved["metadata"] == metadata
        baseline = saved["summary"] if compatible else None
    selected = report["strategies"]["rerank"]["summary"]
    checks = quality_checks(selected, baseline=baseline)
    checks.update(no_retrieval_errors=not report["errors"], baseline_compatible=compatible)
    report["checks"] = checks
    print("阶段3/3：真实接口冒烟（仅--with-agent启用）。", flush=True)
    report["live_checks"] = {"status": "skipped", "reason": "未提供--with-agent；本地评测未调用DeepSeek/MySQL。"}
    if with_agent:
        from app.evaluation_live import run_live_checks
        try:
            with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "rerank"}):
                live = run_live_checks()
            report["live_checks"] = {"status": "passed", "cases": live}
        except (AppError, AssertionError) as exc:
            report["live_checks"] = {"status": "failed", "code": exc.code if isinstance(exc, AppError) else "assertion_failed"}
    report["passed"] = all(checks.values()) and report["live_checks"]["status"] != "failed"
    report["elapsed_seconds"] = round(perf_counter() - started, 2)
    if report["passed"] and (update_baseline or not BASELINE.exists()):
        write_report(BASELINE, {"metadata": metadata, "summary": selected})
        report["baseline_action"] = "created_or_updated"
    else:
        report["baseline_action"] = "compared_existing" if BASELINE.exists() else "not_written"
    write_report(REPORT, report)
    print(json.dumps({"passed": report["passed"], "checks": checks, "live_status": report["live_checks"]["status"], "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))
    if not report["passed"]:
        raise AppError("评测未通过；详见outputs/14-regression-report.json。资料/模型/评测集变更后需先审阅再显式更新基线。", code="evaluation_failed")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-agent", action="store_true", help="运行真实DeepSeek/MySQL冒烟，会产生API费用")
    parser.add_argument("--update-baseline", action="store_true", help="审阅变更后显式更新本地指标基线")
    args = parser.parse_args()
    try:
        verify(with_agent=args.with_agent, update_baseline=args.update_baseline)
    except (AppError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(str(exc) if isinstance(exc, AppError) else "评测执行失败，请检查评测文件和本地环境；未输出原始异常。")
        sys.exit(1)
