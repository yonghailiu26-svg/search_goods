import json
import unittest
from unittest.mock import patch

import httpx

from app.agent import run_agent
from app.config import AppError

COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def tool(arguments, call_id="call_demo"):
    return {"content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": "search_products", "arguments": arguments,
    }}]}


class Step5Tests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {
            "DEEPSEEK_API_KEY": "test-placeholder", "DEEPSEEK_MODEL": "test-model",
            "AGENT_MAX_MODEL_CALLS": "3", "AGENT_MAX_TOOL_CALLS": "3",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_invalid_arguments_return_error_to_model_then_recover(self):
        responses = [tool('{"limit":99}'), tool('{"brand":"得力"}', "call_fixed"), {"content": "找到商品。"}]
        seen = []

        def complete(client, key, payload):
            seen.append(json.loads(json.dumps(payload)))
            return responses[len(seen) - 1], COUNTS

        with patch("app.agent.complete", side_effect=complete), patch("app.agent.search_products", return_value=[{"sku": "demo"}]) as search:
            result = run_agent("换得力，其他不变", current_requirements={"color": "黑色", "spec": "0.5mm", "max_price_fen": 500})
        error = json.loads(seen[1]["messages"][-1]["content"])
        self.assertEqual(error["status"], "invalid_arguments")
        self.assertEqual(error["issues"][0]["field"], "limit")
        self.assertNotIn("products", error)
        search.assert_called_once()
        self.assertEqual(search.call_args.args[0].color, "黑色")
        self.assertEqual(result["model_calls"], 3)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["usage"]["total_tokens"], 45)
        self.assertEqual(seen[2]["tool_choice"], "none")

    def test_unfixed_arguments_never_query_or_publish_fake_success(self):
        with patch("app.agent.complete", side_effect=[(tool('{"sql":"private-canary"}'), COUNTS), ({"content": "找到虚构商品"}, COUNTS)]), patch("app.agent.search_products") as search:
            result = run_agent("查询商品", current_requirements={"brand": "得力"})
        search.assert_not_called()
        self.assertEqual(result["outcome"], "needs_clarification")
        self.assertEqual(result["current_requirements"], {"brand": "得力"})
        self.assertNotIn("虚构", result["answer"])
        self.assertNotIn("private-canary", json.dumps(result))

    def test_empty_query_result_is_successful_business_result(self):
        with patch("app.agent.complete", side_effect=[(tool('{"max_price_fen":1}'), COUNTS), ({"content": "没有匹配商品"}, COUNTS)]), patch("app.agent.search_products", return_value=[]):
            result = run_agent("预算0.01元")
        self.assertEqual(result["outcome"], "no_results")
        self.assertEqual(result["tool_trace"][0]["status"], "no_results")
        self.assertTrue(result["usage_complete"])

    def test_database_failure_stops_instead_of_becoming_no_results(self):
        with patch("app.agent.complete", return_value=(tool('{}'), COUNTS)) as complete, patch("app.agent.search_products", side_effect=AppError("private-db-canary")):
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        self.assertEqual(caught.exception.code, "tool_failed")
        self.assertNotIn("private-db-canary", str(caught.exception))
        self.assertEqual(caught.exception.diagnostics["tool_trace"][0]["status"], "tool_failed")
        complete.assert_called_once()

    def test_total_tool_budget_limits_database_queries(self):
        with patch.dict("os.environ", {"AGENT_MAX_TOOL_CALLS": "1"}), patch("app.agent.complete", return_value=(tool('{}'), COUNTS)) as complete, patch("app.agent.search_products", return_value=[]) as search:
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        self.assertEqual(caught.exception.code, "execution_limit")
        self.assertEqual(complete.call_count, 2)
        search.assert_called_once()

    def test_continuous_tools_cannot_override_last_round_none(self):
        with patch("app.agent.complete", return_value=(tool('{}'), COUNTS)) as complete, patch("app.agent.search_products", return_value=[]) as search:
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        self.assertEqual(caught.exception.code, "execution_limit")
        self.assertEqual(complete.call_count, 3)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(complete.call_args.args[2]["tool_choice"], "none")

    def test_timeout_does_not_retry_and_reports_unknown_usage(self):
        requests = []

        def handler(request):
            requests.append(request)
            raise httpx.ReadTimeout("private-error-canary", request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("app.agent.httpx.Client", return_value=client):
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        self.assertEqual(len(requests), 1)
        self.assertEqual(caught.exception.code, "model_timeout")
        self.assertFalse(caught.exception.diagnostics["usage_complete"])
        self.assertNotIn("private-error-canary", str(caught.exception))

    def test_truncated_response_preserves_reported_usage(self):
        response = httpx.Response(200, json={"choices": [{"message": {"content": "半句"}, "finish_reason": "length"}], "usage": COUNTS})
        client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
        with patch("app.agent.httpx.Client", return_value=client):
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        self.assertEqual(caught.exception.code, "output_truncated")
        self.assertEqual(caught.exception.diagnostics["usage"], COUNTS)
        self.assertTrue(caught.exception.diagnostics["usage_complete"])

    def test_later_timeout_retains_usage_from_completed_model_calls(self):
        failure = AppError("模型请求超时", code="model_timeout")
        with patch("app.agent.complete", side_effect=[(tool('{}'), COUNTS), failure]), patch("app.agent.search_products", return_value=[]):
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        diagnostics = caught.exception.diagnostics
        self.assertEqual(diagnostics["usage"], COUNTS)
        self.assertFalse(diagnostics["usage_complete"])
        self.assertEqual(len(diagnostics["model_trace"]), 2)

    def test_http_error_body_is_not_exposed(self):
        response = httpx.Response(401, json={"error": "private-http-canary"})
        client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
        with patch("app.agent.httpx.Client", return_value=client):
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        self.assertEqual(caught.exception.code, "model_http_error")
        self.assertNotIn("private-http-canary", str(caught.exception))
        self.assertNotIn("private-http-canary", json.dumps(caught.exception.diagnostics))

    def test_malformed_tool_calls_is_not_accepted_as_plain_answer(self):
        with patch("app.agent.complete", return_value=({"tool_calls": {}, "content": "看似正常"}, COUNTS)):
            with self.assertRaises(AppError) as caught:
                run_agent("找商品")
        self.assertEqual(caught.exception.code, "invalid_response")


if __name__ == "__main__":
    unittest.main()
