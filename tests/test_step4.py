from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.config import AppError
from app.main import app
from app.sessions import SessionStore


class Step4Tests(unittest.TestCase):
    def setUp(self):
        self.session_id = "b" * 32
        self.saved = {
            "requirements": {"category": "签字笔", "color": "黑色", "spec": "0.5mm", "max_price_fen": 500},
            "history": [{"role": "user", "content": "找黑色签字笔"}, {"role": "assistant", "content": "已找到"}],
        }

    def test_fresh_store_restores_context_before_agent_and_commits_afterwards(self):
        repository = Mock()
        repository.load_session.side_effect = lambda key: deepcopy(self.saved)
        result = {"answer": "找到得力商品", "current_requirements": {**self.saved["requirements"], "brand": "得力"}}
        with patch("app.main.store", SessionStore(repository=repository)), patch("app.main.run_agent", return_value=result) as agent:
            response = TestClient(app).post("/chat", json={"session_id": self.session_id, "message": "换得力，其他不变"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(agent.call_args.kwargs["current_requirements"], self.saved["requirements"])
        self.assertEqual(agent.call_args.kwargs["history"], self.saved["history"])
        repository.save_round.assert_called_once_with(self.session_id, result["current_requirements"], "换得力，其他不变", result["answer"])

    def test_database_commit_failure_does_not_publish_new_memory_state(self):
        repository = Mock()
        repository.load_session.side_effect = lambda key: deepcopy(self.saved)
        repository.save_round.side_effect = AppError("模拟数据库保存失败")
        store = SessionStore(repository=repository)
        result = {"answer": "新回答", "current_requirements": {"brand": "得力"}}
        with patch("app.main.store", store), patch("app.main.run_agent", return_value=result):
            response = TestClient(app).post("/chat", json={"session_id": self.session_id, "message": "换得力"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(store.get_or_create(self.session_id)[1].requirements, self.saved["requirements"])

    def test_model_failure_does_not_save_round(self):
        repository = Mock()
        repository.load_session.side_effect = lambda key: deepcopy(self.saved)
        with patch("app.main.store", SessionStore(repository=repository)), patch("app.main.run_agent", side_effect=AppError("模拟超时")):
            response = TestClient(app).post("/chat", json={"session_id": self.session_id, "message": "换得力"})
        self.assertEqual(response.status_code, 503)
        repository.save_round.assert_not_called()

    def test_history_endpoint_reads_without_model_and_missing_returns_404(self):
        with patch("app.main.load_session", return_value={"session_id": self.session_id, **self.saved}), patch("app.main.run_agent") as agent:
            response = TestClient(app).get(f"/sessions/{self.session_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["history"], self.saved["history"])
        agent.assert_not_called()
        with patch("app.main.load_session", return_value=None):
            self.assertEqual(TestClient(app).get(f"/sessions/{self.session_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
