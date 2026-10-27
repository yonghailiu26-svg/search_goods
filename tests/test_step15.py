from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from threading import Barrier
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app
from app.package_graph import get_package_graph
from app.schemas import GetProductDetailArgs
from app.workflow_state import new_package_state
from app.workflows import run_package_check


RULE = "KB-PACK-001-C002"
PASSAGE = {"source_id": "KB-PACK-001", "chunk_id": RULE, "title": "包装规则",
           "content": "缺少具体数量不能猜。", "source": "knowledge/KB-PACK-001.md"}
COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
NODES = ["load_rules", "load_detail", "compose_answer"]


def product(args):
    return {"sku": args.sku, "package_notes": "按支销售，未提供盒装数量。"}


def summary(client, key, payload):
    observed = json.loads(payload["messages"][-1]["content"])
    sku = observed["observations"][1]["product"]["sku"]
    return {"content": json.dumps({"claims": [{"text": "当前不能确认盒装数量。",
            "evidence_ids": [RULE, "SKU:" + sku]}], "unknowns": ["实际一盒数量未知。"]})}, dict(COUNTS)


class Step15Tests(unittest.TestCase):
    def setUp(self):
        configuration = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "unit-placeholder", "DEEPSEEK_MODEL": "unit-model"})
        configuration.start()
        self.addCleanup(configuration.stop)

    def test_compilation_has_no_tool_or_model_side_effect(self):
        get_package_graph.cache_clear()
        with patch("app.workflows.search_knowledge") as rules, patch("app.workflows.get_product_detail") as details, patch("app.workflows.complete") as model:
            graph = get_package_graph()
            self.assertIs(graph, get_package_graph())
        rules.assert_not_called()
        details.assert_not_called()
        model.assert_not_called()

    def test_invoke_populates_observations_without_mutating_input_or_storing_key(self):
        initial = new_package_state("DEMO-PEN-0000")
        before = deepcopy(initial)
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", side_effect=product), patch("app.workflows.complete", side_effect=summary):
            final = get_package_graph().invoke(initial)
        self.assertEqual(initial, before)
        self.assertEqual(final["node_trace"], NODES)
        self.assertEqual(final["rules"]["passages"], [PASSAGE])
        self.assertEqual(final["detail"]["product"]["sku"], initial["sku"])
        self.assertEqual(final["usage"], COUNTS)
        self.assertNotIn("unit-placeholder", json.dumps(final))

    def test_cached_graph_keeps_two_concurrent_requests_separate(self):
        skus = ["DEMO-PEN-0000", "DEMO-PEN-0001"]
        rendezvous = Barrier(2)

        def concurrent_detail(args):
            # 确保两次执行确实重叠，不依赖线程调度碰巧并发。
            rendezvous.wait(timeout=5)
            return product(args)

        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", side_effect=concurrent_detail), patch("app.workflows.complete", side_effect=summary), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda sku: run_package_check(GetProductDetailArgs(sku=sku)), skus))
        for sku, result in zip(skus, results):
            self.assertEqual(result["node_trace"], NODES)
            self.assertEqual(result["tool_trace"][1]["arguments"]["sku"], sku)
            references = {ref for claim in result["answer_details"]["claims"] for ref in claim["evidence_ids"]}
            self.assertIn("SKU:" + sku, references)
            self.assertNotIn("SKU:" + next(other for other in skus if other != sku), references)
            self.assertEqual(result["model_calls"], 1)
            self.assertEqual(result["usage"], COUNTS)

    def test_missing_sku_reaches_answer_node_but_needs_no_model_key(self):
        with patch.dict(os.environ):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value=None), patch("app.workflows.complete") as model:
                result = run_package_check(GetProductDetailArgs(sku="DEMO-NOT-EXIST-999"))
        model.assert_not_called()
        self.assertEqual(result["node_trace"], NODES)
        self.assertEqual(result["outcome"], "not_found")
        self.assertEqual(result["model_calls"], 0)

    def test_failed_invocation_does_not_reuse_previous_success_usage_or_observations(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", side_effect=product), patch("app.workflows.complete", side_effect=summary):
            run_package_check(GetProductDetailArgs(sku="DEMO-PEN-0000"))
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", side_effect=product), patch("app.workflows.complete", side_effect=AppError("模拟超时", code="model_timeout")) as model:
            with self.assertRaises(AppError) as caught:
                run_package_check(GetProductDetailArgs(sku="DEMO-PEN-0001"))
        diagnostics = caught.exception.diagnostics
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(diagnostics["tool_trace"]), 2)
        self.assertEqual(len(diagnostics["model_trace"]), 1)
        self.assertEqual(diagnostics["usage"]["total_tokens"], 0)
        self.assertFalse(diagnostics["usage_complete"])
        self.assertEqual(diagnostics["node_trace"], NODES)

    def test_http_error_keeps_known_usage_and_reports_failed_node(self):
        error = AppError("模拟截断", code="output_truncated", diagnostics={"usage": COUNTS})
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", side_effect=product), patch("app.workflows.complete", side_effect=error), TestClient(app) as client:
            response = client.post("/workflows/package-check", json={"sku": "DEMO-PEN-0000"})
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error_code"], "output_truncated")
        self.assertEqual(body["diagnostics"]["usage"], COUNTS)
        self.assertTrue(body["diagnostics"]["usage_complete"])
        self.assertEqual(body["diagnostics"]["node_trace"], NODES)


if __name__ == "__main__":
    unittest.main()
