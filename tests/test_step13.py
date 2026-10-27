import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app
from app.schemas import GetProductDetailArgs
from app.workflows import run_package_check

SKU = "DEMO-PEN-0000"
RULE = "KB-PACK-001-C002"
PASSAGE = {"source_id": "KB-PACK-001", "chunk_id": RULE, "title": "包装规则", "content": "缺少具体数量不能猜。", "source": "knowledge/KB-PACK-001.md"}
PRODUCT = {"sku": SKU, "package_notes": "按支销售，未提供盒装数量。"}
COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def final_message(ids=None):
    return {"content": json.dumps({"claims": [{"text": "当前不能确认盒装数量。", "evidence_ids": ids or [RULE, "SKU:" + SKU]}], "unknowns": ["实际一盒数量未知。"]})}


class Step13Tests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-placeholder", "DEEPSEEK_MODEL": "test-model"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_fixed_order_two_tools_one_model_and_no_model_tools(self):
        order = []
        def rules(args):
            order.append("rules")
            return [PASSAGE]
        def detail(args):
            order.append("detail")
            self.assertEqual(args.sku, SKU)
            return PRODUCT
        def complete(client, key, payload):
            order.append("summary")
            self.assertNotIn("tools", payload)
            data = json.loads(payload["messages"][-1]["content"])
            self.assertEqual(data["observations"][0]["passages"][0]["content"], PASSAGE["content"])
            self.assertEqual(data["observations"][1]["product"], PRODUCT)
            return final_message(), COUNTS
        with patch("app.workflows.search_knowledge", side_effect=rules), patch("app.workflows.get_product_detail", side_effect=detail), patch("app.workflows.complete", side_effect=complete):
            result = run_package_check(GetProductDetailArgs(sku=SKU))
        self.assertEqual(order, ["rules", "detail", "summary"])
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(result["execution_mode"], "workflow")
        self.assertEqual(result["usage"], COUNTS)
        self.assertEqual(result["sources"][0]["citation_id"], RULE)

    def test_missing_product_short_circuits_without_model(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value=None), patch("app.workflows.complete") as model:
            result = run_package_check(GetProductDetailArgs(sku=SKU))
        model.assert_not_called()
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["outcome"], "not_found")
        self.assertEqual(result["usage"]["total_tokens"], 0)

    def test_null_packaging_adds_program_gap(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value={**PRODUCT, "package_notes": None}), patch("app.workflows.complete", return_value=(final_message(), COUNTS)):
            result = run_package_check(GetProductDetailArgs(sku=SKU))
        self.assertTrue(any("未提供包装说明" in text for text in result["answer_details"]["unknowns"]))

    def test_rule_failure_stops_before_database_and_redacts_internal_error(self):
        with patch("app.workflows.search_knowledge", side_effect=AppError("private-canary")), patch("app.workflows.get_product_detail") as database, patch("app.workflows.complete") as model:
            with self.assertRaises(AppError) as caught:
                run_package_check(GetProductDetailArgs(sku=SKU))
        database.assert_not_called()
        model.assert_not_called()
        self.assertNotIn("private-canary", str(caught.exception))
        self.assertEqual(caught.exception.diagnostics["tool_trace"][-1]["tool"], "search_knowledge")

    def test_detail_failure_keeps_first_observation(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", side_effect=AppError("private-canary")):
            with self.assertRaises(AppError) as caught:
                run_package_check(GetProductDetailArgs(sku=SKU))
        trace = caught.exception.diagnostics["tool_trace"]
        self.assertEqual([row["tool"] for row in trace], ["search_knowledge", "get_product_detail"])
        self.assertEqual(trace[-1]["status"], "tool_failed")

    def test_model_timeout_has_unknown_usage_and_does_not_retry(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value=PRODUCT), patch("app.workflows.complete", side_effect=AppError("timeout", code="model_timeout")) as model:
            with self.assertRaises(AppError) as caught:
                run_package_check(GetProductDetailArgs(sku=SKU))
        self.assertEqual(model.call_count, 1)
        self.assertFalse(caught.exception.diagnostics["usage_complete"])

    def test_invalid_reference_stops_and_preserves_known_usage(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value=PRODUCT), patch("app.workflows.complete", return_value=(final_message([RULE, "SKU:FAKE"]), COUNTS)):
            with self.assertRaises(AppError) as caught:
                run_package_check(GetProductDetailArgs(sku=SKU))
        self.assertEqual(caught.exception.code, "invalid_evidence")
        self.assertEqual(caught.exception.diagnostics["usage"], COUNTS)

    def test_summary_cannot_request_an_extra_tool(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value=PRODUCT), patch("app.workflows.complete", return_value=({"tool_calls": [{"id": "extra"}]}, COUNTS)):
            with self.assertRaises(AppError) as caught:
                run_package_check(GetProductDetailArgs(sku=SKU))
        self.assertEqual(caught.exception.code, "workflow_contract_error")

    def test_endpoint_rejects_invalid_sku_or_session_before_execution(self):
        with patch("app.main.run_package_check") as workflow, TestClient(app) as client:
            for body in ({"sku": "../../secret"}, {"sku": SKU, "session_id": "0" * 32}):
                response = client.post("/workflows/package-check", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("secret", response.text)
        workflow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
