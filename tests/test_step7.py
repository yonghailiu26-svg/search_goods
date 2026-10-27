import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.agent import run_agent
from app.config import AppError
from app.knowledge import PROJECT_ROOT, search_knowledge
from app.schemas import SearchKnowledgeArgs
from app.tool_runner import execute_knowledge

COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
PACK = {
    "source_id": "KB-PACK-001", "title": "包装换算规则", "source": "knowledge/KB-PACK-001.md",
    "content": "盒支换算以具体SKU提供的包装数量为准，缺失时不能猜测。", "score": 1,
}


def call(query):
    return {"content": None, "tool_calls": [{"id": "call_rules", "type": "function", "function": {
        "name": "search_knowledge", "arguments": json.dumps({"query": query}, ensure_ascii=False),
    }}]}


class Step7Tests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {
            "DEEPSEEK_API_KEY": "test-placeholder", "DEEPSEEK_MODEL": "test-model",
            "AGENT_MAX_MODEL_CALLS": "3", "AGENT_MAX_TOOL_CALLS": "3",
            "KNOWLEDGE_RETRIEVAL": "keyword",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def test_keyword_retrieval_returns_rule_body_and_real_source(self):
        passages = search_knowledge(SearchKnowledgeArgs(query="为什么一盒不能默认12支，包装怎么换算？"))
        self.assertEqual(passages[0]["source_id"], "KB-PACK-001")
        self.assertIn("不能对所有商品统一假定每盒12支", passages[0]["content"])
        self.assertTrue((PROJECT_ROOT / passages[0]["source"]).is_file())

    def test_keyword_ranking_and_limit(self):
        passages = search_knowledge(SearchKnowledgeArgs(query="价格 单价 预算", limit=1))
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0]["source_id"], "KB-PRICE-001")
        self.assertEqual(passages[0]["score"], 3)

    def test_no_match_is_empty_instead_of_unrelated_fallback(self):
        self.assertEqual(search_knowledge(SearchKnowledgeArgs(query="保修政策")), [])
        self.assertEqual(search_knowledge(SearchKnowledgeArgs(query="../../.env.dev")), [])

    def test_missing_or_malformed_corpus_is_error_not_no_match(self):
        work = PROJECT_ROOT / "work"
        work.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=work) as directory:
            with patch("app.knowledge.KNOWLEDGE_DIR", Path(directory)):
                with self.assertRaises(AppError) as caught:
                    search_knowledge(SearchKnowledgeArgs(query="包装"))
                self.assertEqual(caught.exception.code, "knowledge_unavailable")
                (Path(directory) / "KB-BROKEN-001.md").write_text("not a valid rule", encoding="utf-8")
                with self.assertRaises(AppError):
                    search_knowledge(SearchKnowledgeArgs(query="包装"))

    def test_invalid_arguments_do_not_run_retrieval_or_echo_input(self):
        for arguments in ('{"query":" "}', '{"query":"包装","limit":4}', '{"query":"包装","file":"private-canary"}'):
            search = Mock()
            result, requirements, trace = execute_knowledge(arguments, {"brand": "得力"}, search=search)
            self.assertEqual(result["status"], "invalid_arguments")
            self.assertEqual(requirements, {"brand": "得力"})
            self.assertNotIn("private-canary", json.dumps(trace))
            search.assert_not_called()

    def test_retrieval_does_not_modify_search_state(self):
        current = {"brand": "得力", "color": "黑色", "max_price_fen": 500}
        result, after, _ = execute_knowledge('{"query":"包装"}', current, search=Mock(return_value=[PACK]))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(after, current)
        self.assertIsNot(after, current)

    def test_agent_sends_retrieved_text_to_next_model_request(self):
        snapshots = []

        def complete(client, key, payload):
            snapshots.append(json.loads(json.dumps(payload)))
            return (call("包装换算") if len(snapshots) == 1 else {"content": "包装数量须查具体SKU，不能猜。[KB-PACK-001]"}), COUNTS

        current = {"brand": "得力", "max_price_fen": 500}
        with patch("app.agent.complete", side_effect=complete), patch("app.agent.search_knowledge", return_value=[PACK]), patch("app.agent.search_products") as products:
            result = run_agent("包装换算规则是什么", current_requirements=current)
        products.assert_not_called()
        returned = json.loads(snapshots[1]["messages"][-1]["content"])
        self.assertEqual(returned["passages"][0]["content"], PACK["content"])
        self.assertEqual(snapshots[1]["messages"][-1]["role"], "tool")
        self.assertEqual(result["sources"][0]["source_id"], "KB-PACK-001")
        self.assertEqual(result["current_requirements"], current)
        self.assertIn("search_knowledge", [tool["function"]["name"] for tool in snapshots[0]["tools"]])

    def test_unretrieved_or_missing_citation_is_rejected(self):
        for answer in ("规则是这样。[KB-FAKE-999]", "规则是这样，但没有来源标识。"):
            with patch("app.agent.complete", side_effect=[(call("包装"), COUNTS), ({"content": answer}, COUNTS)]), patch("app.agent.search_knowledge", return_value=[PACK]):
                with self.assertRaises(AppError) as caught:
                    run_agent("包装规则")
                self.assertEqual(caught.exception.code, "invalid_citation")

    def test_no_evidence_cannot_become_invented_policy(self):
        with patch("app.agent.complete", side_effect=[(call("保修政策"), COUNTS), ({"content": "保修99年。[KB-FAKE-999]"}, COUNTS)]), patch("app.agent.search_knowledge", return_value=[]):
            result = run_agent("保修多久")
        self.assertEqual(result["outcome"], "no_knowledge")
        self.assertEqual(result["sources"], [])
        self.assertNotIn("99", result["answer"])

    def test_unavailable_retrieval_is_not_reported_as_no_knowledge(self):
        with patch("app.agent.complete", return_value=(call("包装"), COUNTS)), patch("app.agent.search_knowledge", side_effect=AppError("private-canary")):
            with self.assertRaises(AppError) as caught:
                run_agent("包装规则")
        self.assertEqual(caught.exception.code, "tool_failed")
        self.assertEqual(caught.exception.diagnostics["tool_trace"][0]["tool"], "search_knowledge")
        self.assertNotIn("private-canary", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
