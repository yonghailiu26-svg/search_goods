import json
import unittest
from unittest.mock import Mock, patch

from app.agent import run_agent
from app.config import AppError
from app.tool_runner import execute_detail

COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def call(name, arguments, call_id):
    return {"content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False),
    }}]}


class Step6Tests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {
            "DEEPSEEK_API_KEY": "test-placeholder", "DEEPSEEK_MODEL": "test-model",
            "AGENT_MAX_MODEL_CALLS": "3", "AGENT_MAX_TOOL_CALLS": "3",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_search_then_detail_dispatches_to_different_functions(self):
        product = {"sku": "DEMO-PEN-0000"}
        responses = [call("search_products", {"brand": "得力"}, "search_call"),
                     call("get_product_detail", {"sku": product["sku"]}, "detail_call"), {"content": "商品说明"}]
        payloads = []

        def complete(client, key, payload):
            payloads.append(json.loads(json.dumps(payload)))
            return responses[len(payloads) - 1], COUNTS

        with patch("app.agent.complete", side_effect=complete), patch("app.agent.search_products", return_value=[product]) as search, patch("app.agent.get_product_detail", return_value={**product, "description": "练习说明"}) as detail:
            result = run_agent("找得力笔并看详情", current_requirements={"color": "黑色", "max_price_fen": 500})
        search.assert_called_once()
        detail.assert_called_once()
        self.assertEqual(detail.call_args.args[0].sku, product["sku"])
        self.assertEqual([row["tool"] for row in result["tool_trace"]], ["search_products", "get_product_detail"])
        self.assertEqual(result["current_requirements"], {"brand": "得力", "color": "黑色", "max_price_fen": 500, "limit": 5})
        self.assertTrue({"search_products", "get_product_detail"}.issubset({tool["function"]["name"] for tool in payloads[0]["tools"]}))
        self.assertEqual(json.loads(payloads[1]["messages"][-1]["content"])["products"], [product])
        self.assertEqual(payloads[2]["messages"][-1]["tool_call_id"], "detail_call")

    def test_direct_detail_does_not_search_or_change_requirements(self):
        current = {"brand": "晨光", "color": "蓝色", "spec": "0.7mm", "max_price_fen": 400}
        with patch("app.agent.complete", side_effect=[(call("get_product_detail", {"sku": "DEMO-PEN-0000"}, "detail"), COUNTS), ({"content": "得力商品详情"}, COUNTS)]), patch("app.agent.search_products") as search, patch("app.agent.get_product_detail", return_value={"sku": "DEMO-PEN-0000"}):
            result = run_agent("查看DEMO-PEN-0000", current_requirements=current)
        search.assert_not_called()
        self.assertEqual(result["current_requirements"], current)

    def test_detail_missing_sku_is_not_found_and_keeps_conditions(self):
        result, requirements, trace = execute_detail('{"sku":"DEMO-MISSING"}', {"brand": "得力"}, get_detail=Mock(return_value=None))
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["product"])
        self.assertEqual(requirements, {"brand": "得力"})
        self.assertEqual(trace["tool"], "get_product_detail")

    def test_invalid_detail_arguments_do_not_query_or_echo_values(self):
        for arguments in ('{}', '{"sku":7}', '{"sku":"private-canary\u0027 OR 1=1"}', '{"sku":"DEMO","sql":"private-canary"}'):
            detail = Mock()
            result, requirements, trace = execute_detail(arguments, {"color": "黑色"}, get_detail=detail)
            self.assertEqual(result["status"], "invalid_arguments")
            self.assertNotIn("private-canary", json.dumps(trace))
            self.assertEqual(requirements, {"color": "黑色"})
            detail.assert_not_called()

    def test_detail_failure_trace_names_the_actual_tool(self):
        with patch("app.agent.complete", return_value=(call("get_product_detail", {"sku": "DEMO-PEN-0000"}, "detail"), COUNTS)), patch("app.agent.get_product_detail", side_effect=AppError("不可公开的原始错误")):
            with self.assertRaises(AppError) as caught:
                run_agent("查看SKU")
        self.assertEqual(caught.exception.code, "tool_failed")
        self.assertEqual(caught.exception.diagnostics["tool_trace"][0]["tool"], "get_product_detail")


if __name__ == "__main__":
    unittest.main()
