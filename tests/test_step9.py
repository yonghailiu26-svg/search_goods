import json
import unittest
from unittest.mock import patch

from app.agent import run_agent
from app.config import AppError
from app.evidence import collect_evidence, render_evidence_answer, validate_evidence_answer

COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
RULE_ID = "KB-PACK-001-C002"
SKU = "DEMO-PEN-0000"
PASSAGE = {"source_id": "KB-PACK-001", "chunk_id": RULE_ID, "source": "knowledge/KB-PACK-001.md",
           "title": "包装规则", "content": "未提供盒装数量时不能猜测。"}
PRODUCT = {"sku": SKU, "name": "练习签字笔", "price_fen": 150, "package_notes": "按支销售，未提供盒装数量。"}


def observations(product=PRODUCT, passages=None):
    passages = [PASSAGE] if passages is None else passages
    return [
        {"tool": "search_knowledge", "status": "ok" if passages else "no_knowledge", "passages": passages},
        {"tool": "get_product_detail", "status": "ok" if product else "not_found", "product": product, "arguments": {"sku": SKU}},
    ]


def model_answer(refs=None):
    return json.dumps({"claims": [{"text": "包装说明未提供盒装数量，按规则无法确认一盒支数。", "evidence_ids": refs or [RULE_ID, f"SKU:{SKU}"]}],
                       "unknowns": ["该SKU具体一盒多少支仍未知。"]}, ensure_ascii=False)


class Step9Tests(unittest.TestCase):
    def test_single_tool_kind_does_not_enable_mixed_contract(self):
        rows = observations()
        self.assertIsNone(collect_evidence(rows[:1]))
        self.assertIsNone(collect_evidence(rows[1:]))
        self.assertIsNone(collect_evidence([rows[0], {"tool": "get_product_detail", "status": "invalid_arguments"}]))

    def test_collects_only_actual_rule_and_product_evidence(self):
        context = collect_evidence(observations())
        self.assertEqual(context["items"], [{"id": RULE_ID, "kind": "rule"}, {"id": f"SKU:{SKU}", "kind": "product", "sku": SKU}])
        answer = validate_evidence_answer(model_answer(), context)
        text, details = render_evidence_answer(answer, context)
        self.assertIn(f"[{RULE_ID}]", text)
        self.assertIn(f"[SKU:{SKU}]", text)
        self.assertEqual(details["claims"][0]["evidence_ids"], [RULE_ID, f"SKU:{SKU}"])

    def test_rejects_unknown_sku_chunk_and_omitted_evidence_kind(self):
        context = collect_evidence(observations())
        for refs in ([RULE_ID, "SKU:FAKE"], ["KB-PACK-001-C999", f"SKU:{SKU}"], [RULE_ID], [f"SKU:{SKU}"]):
            with self.assertRaises(AppError) as caught:
                validate_evidence_answer(model_answer(refs), context)
            self.assertEqual(caught.exception.code, "invalid_evidence")

    def test_missing_rule_and_product_do_not_get_citable_ids(self):
        context = collect_evidence(observations(product=None, passages=[]))
        self.assertEqual(context["items"], [])
        answer = validate_evidence_answer('{"claims":[],"unknowns":[]}', context)
        text, details = render_evidence_answer(answer, context)
        self.assertIn("未查到SKU", text)
        self.assertIn("未命中资料", text)
        self.assertEqual(len(details["unknowns"]), 2)
        with self.assertRaises(AppError):
            validate_evidence_answer(model_answer(), context)

    def test_null_package_notes_produce_gap_even_if_model_omits_it(self):
        product = {**PRODUCT, "package_notes": None}
        context = collect_evidence(observations(product=product))
        answer = validate_evidence_answer(json.dumps({"claims": [{"text": "需要查证。", "evidence_ids": [RULE_ID, f"SKU:{SKU}"]}], "unknowns": []}), context)
        text, details = render_evidence_answer(answer, context)
        self.assertIn("未提供包装说明", text)
        self.assertTrue(details["unknowns"])

    def test_no_rule_uses_product_claim_and_puts_missing_policy_in_unknowns(self):
        context = collect_evidence(observations(passages=[]))
        content = json.dumps({"claims": [{"text": "该商品按支销售。", "evidence_ids": [f"SKU:{SKU}"]}], "unknowns": ["无法确认保修期限。"]})
        answer = validate_evidence_answer(content, context)
        text, details = render_evidence_answer(answer, context)
        self.assertIn("未命中资料", text)
        self.assertEqual(len(details["claims"]), 1)
        broken = json.loads(content)
        broken["claims"].append({"text": "没有规则证据。", "evidence_ids": []})
        with self.assertRaises(AppError):
            validate_evidence_answer(json.dumps(broken), context)

    def test_malformed_or_unreferenced_claim_is_not_used_as_answer(self):
        context = collect_evidence(observations())
        for content in ("随便回答一盒12支", '{"claims":[{"text":"","evidence_ids":[]}],"unknowns":[]}', '{"claims":[],"unknowns":[" "]}'):
            with self.assertRaises(AppError):
                validate_evidence_answer(content, context)

    def run_mixed(self, final_content):
        snapshots = []
        call = {"content": None, "tool_calls": [
            {"id": "rules", "type": "function", "function": {"name": "search_knowledge", "arguments": '{"query":"盒装"}'}},
            {"id": "detail", "type": "function", "function": {"name": "get_product_detail", "arguments": json.dumps({"sku": SKU})}},
        ]}

        def complete(client, key, payload):
            snapshots.append(json.loads(json.dumps(payload)))
            return (call if len(snapshots) == 1 else {"content": final_content}), COUNTS

        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-placeholder", "DEEPSEEK_MODEL": "test-model", "AGENT_MAX_MODEL_CALLS": "3", "AGENT_MAX_TOOL_CALLS": "3"}), patch("app.agent.complete", side_effect=complete), patch("app.agent.search_knowledge", return_value=[PASSAGE]), patch("app.agent.get_product_detail", return_value=PRODUCT):
            return run_agent("按规则查询该商品盒装数量", current_requirements={"brand": "得力"}), snapshots

    def test_agent_gives_actual_tool_bodies_and_contract_before_summary(self):
        result, snapshots = self.run_mixed(model_answer())
        self.assertEqual(result["current_requirements"], {"brand": "得力"})
        self.assertEqual(result["model_calls"], 2)
        self.assertEqual(len(result["answer_details"]["claims"]), 1)
        tools = [message for message in snapshots[1]["messages"] if message["role"] == "tool"]
        self.assertEqual(len(tools), 2)
        self.assertEqual(json.loads(tools[0]["content"])["passages"][0]["content"], PASSAGE["content"])
        self.assertEqual(json.loads(tools[1]["content"])["product"], PRODUCT)
        self.assertIn("SKU:" + SKU, snapshots[1]["messages"][-1]["content"])
        self.assertIn("claims", snapshots[1]["messages"][-1]["content"])

    def test_agent_rejects_invalid_evidence_and_retains_usage_diagnostics(self):
        with self.assertRaises(AppError) as caught:
            self.run_mixed(model_answer([RULE_ID, "SKU:FAKE"]))
        self.assertEqual(caught.exception.code, "invalid_evidence")
        self.assertEqual(caught.exception.diagnostics["usage"]["total_tokens"], 30)
        self.assertEqual(len(caught.exception.diagnostics["tool_trace"]), 2)


if __name__ == "__main__":
    unittest.main()
