import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agent import run_agent
from app.config import AppError
from app.main import app
from app.schemas import SearchProductsArgs
from app.sessions import SessionStore, merge_requirements

BASE = {"category": "签字笔", "color": "黑色", "spec": "0.5mm", "max_price_fen": 500, "limit": 3}


class Step3Tests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"DEEPSEEK_API_KEY": "unit-test-placeholder", "DEEPSEEK_MODEL": "test", "AGENT_MAX_MODEL_CALLS": "3"})
        environment.start()
        self.addCleanup(environment.stop)

    def test_brand_patch_preserves_every_other_condition_and_limit(self):
        merged = merge_requirements(BASE, SearchProductsArgs(brand="得力"))
        self.assertEqual(merged.model_dump(exclude_none=True), {**BASE, "brand": "得力"})
        self.assertNotIn("brand", BASE)

    def test_missing_field_preserved_but_explicit_null_clears(self):
        current = {**BASE, "brand": "得力"}
        kept = merge_requirements(current, SearchProductsArgs())
        cleared = merge_requirements(current, SearchProductsArgs(brand=None))
        self.assertEqual(kept.brand, "得力")
        self.assertIsNone(cleared.brand)
        self.assertEqual(cleared.color, "黑色")

    def test_category_change_clears_old_product_specific_conditions(self):
        current = {**BASE, "brand": "得力", "keyword": "速干"}
        result = merge_requirements(current, SearchProductsArgs(category="橡皮"))
        for name in ("brand", "keyword", "color", "spec"):
            self.assertIsNone(getattr(result, name))
        self.assertEqual(result.max_price_fen, 500)
        self.assertEqual(result.limit, 3)
        explicit = merge_requirements(current, SearchProductsArgs(category="橡皮", color="白色"))
        self.assertEqual(explicit.color, "白色")

    def test_same_category_does_not_clear_old_conditions(self):
        self.assertEqual(merge_requirements(BASE, SearchProductsArgs(category="签字笔")).color, "黑色")

    def test_agent_queries_merged_conditions_and_returns_changes(self):
        counts = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        tool_message = {"content": None, "tool_calls": [{
            "id": "test_call", "type": "function",
            "function": {"name": "search_products", "arguments": '{"brand":"得力"}'},
        }]}
        with patch("app.agent.complete", side_effect=[(tool_message, counts), ({"content": "找到候选。"}, counts)]) as complete:
            with patch("app.agent.search_products", return_value=[]) as search:
                result = run_agent("换得力，其他不变", current_requirements=BASE, history=[{"role": "user", "content": "先找签字笔"}])
        queried = search.call_args.args[0]
        self.assertEqual(queried.color, "黑色")
        self.assertEqual(queried.brand, "得力")
        self.assertEqual(queried.limit, 3)
        self.assertEqual(result["tool_trace"][0]["changes"], {"brand": "得力"})
        self.assertIn("先找签字笔", str(complete.call_args.args[2]["messages"]))

    def test_api_sessions_are_isolated_and_failed_round_is_not_saved(self):
        local_store = SessionStore()

        def successful(question, *, current_requirements, history):
            args = merge_requirements(current_requirements, SearchProductsArgs(brand=question))
            return {"answer": "回答", "current_requirements": args.model_dump(exclude_none=True)}

        with patch("app.main.store", local_store), patch("app.main.run_agent", side_effect=successful):
            with TestClient(app) as client:
                first = client.post("/chat", json={"message": "得力"}).json()
                second = client.post("/chat", json={"message": "晨光"}).json()
                first_session = local_store.get_or_create(first["session_id"])[1]
                second_session = local_store.get_or_create(second["session_id"])[1]
                self.assertNotEqual(first["session_id"], second["session_id"])
                self.assertEqual(first_session.requirements["brand"], "得力")
                self.assertEqual(second_session.requirements["brand"], "晨光")
                with patch("app.main.run_agent", side_effect=AppError("模拟网络失败")):
                    failed = client.post("/chat", json={"message": "换齐心", "session_id": first["session_id"]})
                self.assertEqual(failed.status_code, 503)
                self.assertEqual(first_session.requirements["brand"], "得力")
                self.assertEqual(len(first_session.history), 2)

    def test_unknown_session_is_not_silently_recreated(self):
        with patch("app.main.store", SessionStore()), patch("app.main.run_agent") as agent:
            response = TestClient(app).post("/chat", json={"message": "换得力", "session_id": "a" * 32})
        self.assertEqual(response.status_code, 404)
        agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
