import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent import run_agent
from app.config import AppError
from app.main import app
from app.products import SearchProductsArgs


class Step2Tests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {
            "DEEPSEEK_API_KEY": "unit-test-placeholder",
            "DEEPSEEK_MODEL": "unit-test-model",
            "AGENT_MAX_MODEL_CALLS": "3",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_reject_unsafe_tool_arguments(self):
        for arguments in ({"limit": 1000}, {"max_price_fen": -1}, {"sql": "DROP TABLE products"}, {"limit": "5"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                SearchProductsArgs.model_validate(arguments)

    def test_api_rejects_empty_message_without_calling_model(self):
        with patch("app.main.run_agent") as agent:
            response = TestClient(app).post("/chat", json={"message": "  "})
            self.assertEqual(response.status_code, 422)
            agent.assert_not_called()

    def test_tool_result_is_paired_and_sent_back_to_model(self):
        requests = []

        def handler(request):
            import json
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_test", "type": "function", "function": {
                        "name": "search_products", "arguments": '{"brand":"得力","max_price_fen":500}',
                    },
                }]}
            else:
                tool_message = body["messages"][-1]
                self.assertEqual(tool_message["role"], "tool")
                self.assertEqual(tool_message["tool_call_id"], "call_test")
                self.assertEqual(json.loads(tool_message["content"])["products"], [])
                message = {"role": "assistant", "content": "未找到匹配商品。"}
            return httpx.Response(200, json={
                "choices": [{"message": message, "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            })

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch("app.agent.httpx.Client", return_value=client), patch("app.agent.search_products", return_value=[]) as search:
            result = run_agent("查询商品")
        search.assert_called_once()
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(result["usage"]["total_tokens"], 30)

    def test_unknown_tool_is_never_executed(self):
        message = {"tool_calls": [{"function": {"name": "execute_sql", "arguments": "{}"}}]}
        response = httpx.Response(200, json={
            "choices": [{"message": message, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
        client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
        with patch("app.agent.httpx.Client", return_value=client), patch("app.agent.search_products") as search:
            with self.assertRaises(AppError):
                run_agent("查询商品")
            search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
