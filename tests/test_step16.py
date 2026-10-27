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
from app.workflows import reply_package_not_found, route_package_detail, run_package_check


SKU = "DEMO-PEN-0000"
MISSING = "DEMO-NOT-EXIST-999"
RULE = "KB-PACK-001-C002"
PASSAGE = {"source_id": "KB-PACK-001", "chunk_id": RULE, "title": "包装规则",
           "content": "未提供数量就明确未知。", "source": "knowledge/KB-PACK-001.md"}
PRODUCT = {"sku": SKU, "package_notes": None}
COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
FOUND_PATH = ["load_rules", "load_detail", "compose_answer"]
MISSING_PATH = ["load_rules", "load_detail", "reply_not_found"]


def summary(client, key, payload):
    return {"content": json.dumps({"claims": [{"text": "该商品没有可确认的盒装数量。",
            "evidence_ids": [RULE, "SKU:" + SKU]}], "unknowns": ["盒装数量未知。"]})}, dict(COUNTS)


def observed(detail):
    state = new_package_state(SKU)
    state["detail"] = detail
    state["node_trace"] = ["load_rules", "load_detail"]
    return state


class Step16Tests(unittest.TestCase):
    def setUp(self):
        get_package_graph.cache_clear()
        self.addCleanup(get_package_graph.cache_clear)
        configuration = patch.dict(os.environ, {"DEEPSEEK_API_KEY": "unit-placeholder", "DEEPSEEK_MODEL": "unit-model"})
        configuration.start()
        self.addCleanup(configuration.stop)

    def test_router_selects_from_facts_without_mutation_or_tool_calls(self):
        cases = (({"status": "ok", "product": PRODUCT}, "summarize"),
                 ({"status": "not_found", "product": None}, "not_found"))
        with patch("app.workflows.search_knowledge") as rules, patch("app.workflows.get_product_detail") as database, patch("app.workflows.complete") as model:
            for detail, expected in cases:
                with self.subTest(expected=expected):
                    state = observed(detail)
                    before = deepcopy(state)
                    self.assertEqual(route_package_detail(state), expected)
                    self.assertEqual(state, before)
        rules.assert_not_called()
        database.assert_not_called()
        model.assert_not_called()

    def test_router_rejects_missing_contradictory_and_wrong_sku_observations(self):
        for detail in (None, {}, {"status": "not_found"}, {"status": "ok", "product": None},
                       {"status": "not_found", "product": PRODUCT}, {"status": "tool_failed", "product": None},
                       {"status": "ok", "product": {}}, {"status": "ok", "product": {"sku": "WRONG-SKU"}}):
            with self.subTest(detail=detail):
                state = observed(detail)
                before = deepcopy(state)
                with self.assertRaises(AppError) as caught:
                    route_package_detail(state)
                self.assertEqual(caught.exception.code, "workflow_state_invalid")
                self.assertEqual(state, before)

    def test_missing_sku_bypasses_summary_node(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value=None), \
                patch("app.workflows.compose_package_answer", autospec=True, side_effect=AssertionError("must not run")) as skipped, \
                patch("app.workflows.complete") as model:
            result = run_package_check(GetProductDetailArgs(sku=MISSING))
        skipped.assert_not_called()
        model.assert_not_called()
        self.assertEqual(result["node_trace"], MISSING_PATH)
        self.assertEqual(result["outcome"], "not_found")
        self.assertEqual(result["usage"]["total_tokens"], 0)
        self.assertEqual(result["model_calls"], 0)

    def test_present_sku_bypasses_direct_reply_even_without_packaging_notes(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", return_value=PRODUCT), \
                patch("app.workflows.reply_package_not_found", autospec=True, side_effect=AssertionError("must not run")) as skipped, \
                patch("app.workflows.complete", side_effect=summary) as model:
            result = run_package_check(GetProductDetailArgs(sku=SKU))
        skipped.assert_not_called()
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["node_trace"], FOUND_PATH)
        self.assertEqual(result["outcome"], "answered")
        self.assertTrue(any("未提供包装说明" in text for text in result["answer_details"]["unknowns"]))

    def test_database_failure_is_not_routed_as_not_found(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), \
                patch("app.workflows.get_product_detail", side_effect=AppError("internal-canary")), \
                patch("app.workflows.reply_package_not_found", autospec=True) as reply, \
                patch("app.workflows.compose_package_answer", autospec=True) as compose, TestClient(app) as client:
            response = client.post("/workflows/package-check", json={"sku": SKU})
        reply.assert_not_called()
        compose.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error_code"], "tool_failed")
        self.assertEqual(response.json()["diagnostics"]["node_trace"], ["load_rules", "load_detail"])
        self.assertNotIn("internal-canary", response.text)

    def test_inconsistent_tool_observation_stops_with_503(self):
        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), \
                patch("app.workflows.get_product_detail", return_value={"sku": "WRONG-SKU"}), \
                patch("app.workflows.complete") as model, TestClient(app) as client:
            response = client.post("/workflows/package-check", json={"sku": SKU})
        model.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error_code"], "workflow_state_invalid")

    def test_concurrent_found_and_missing_requests_take_only_their_own_paths(self):
        rendezvous = Barrier(2)

        def detail(args):
            rendezvous.wait(timeout=5)
            return PRODUCT if args.sku == SKU else None

        with patch("app.workflows.search_knowledge", return_value=[PASSAGE]), patch("app.workflows.get_product_detail", side_effect=detail), \
                patch("app.workflows.complete", side_effect=summary) as model, ThreadPoolExecutor(max_workers=2) as pool:
            get_package_graph()
            found, missing = list(pool.map(lambda sku: run_package_check(GetProductDetailArgs(sku=sku)), (SKU, MISSING)))
        self.assertEqual(model.call_count, 1)
        self.assertEqual(found["node_trace"], FOUND_PATH)
        self.assertEqual(missing["node_trace"], MISSING_PATH)
        self.assertEqual(found["usage"], COUNTS)
        self.assertEqual(missing["usage"]["total_tokens"], 0)
        self.assertEqual(missing["answer_details"], None)

    def test_reply_node_rejects_an_existing_product(self):
        with self.assertRaises(AppError) as caught:
            reply_package_not_found(observed({"status": "ok", "product": PRODUCT}))
        self.assertEqual(caught.exception.code, "workflow_state_invalid")


if __name__ == "__main__":
    unittest.main()
