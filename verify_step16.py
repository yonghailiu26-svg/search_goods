"""第十六课：复用业务基线对照，检查条件路由；--with-live会调用真实API。"""
import argparse
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
import sys

from app.config import AppError
from app.evaluation import write_report
from verify_step15 import BASELINE, live_checks, offline_comparison


OUTPUT = Path(__file__).resolve().parent / "outputs" / "16-conditional-routing-evaluation.json"


def verify(with_live=False):
    report = {
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "development_baseline_tag": "lesson-15", "business_reference_tag": BASELINE,
        "langgraph_version": version("langgraph"), "offline": [], "passed": False,
        "paths": {"found": ["load_rules", "load_detail", "compose_answer"],
                  "not_found": ["load_rules", "load_detail", "reply_not_found"]},
        "live_checks": {"status": "skipped", "reason": "未提供--with-live；未请求真实模型或MySQL。"},
    }
    try:
        # 复用原六个业务对照场景；不会调用第15课脚本的main或覆盖第15课报告。
        report["offline"] = offline_comparison()
        print("6个业务基线场景一致，未找到商品已走独立答复路径。", flush=True)
        if with_live:
            report["live_checks"] = {"status": "passed", "cases": live_checks()}
        report["passed"] = True
    except (AppError, AssertionError, OSError) as exc:
        report["error_code"] = exc.code if isinstance(exc, AppError) else "verification_failed"
        if with_live and report["offline"]:
            report["live_checks"] = {"status": "failed"}
        raise AppError("第16课验收未通过，已保存本次报告。", code="verification_failed") from None
    finally:
        write_report(OUTPUT, report)
    print("第16课验收通过；报告位于outputs/16-conditional-routing-evaluation.json。", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-live", action="store_true", help="额外运行真实RAG/MySQL/DeepSeek，会产生API费用")
    args = parser.parse_args()
    try:
        verify(with_live=args.with_live)
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
