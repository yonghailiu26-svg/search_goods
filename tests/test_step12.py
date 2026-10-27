from copy import deepcopy
import math
import unittest
from unittest.mock import Mock, patch

from app.config import AppError
from app.knowledge import search_knowledge
from app.reranking import get_reranker, rerank_passages, score_pairs
from app.schemas import SearchKnowledgeArgs


def passage(key, score):
    return {"chunk_id": key, "title": "练习标题", "content": "正文" + key, "score": score,
            "score_kind": "rrf", "retrieval": "hybrid", "source": "knowledge/test.md", "source_version": "version"}


class Step12Tests(unittest.TestCase):
    def test_scores_pairs_and_reorders_without_rewriting_body(self):
        candidates = [passage("A", 0.03), passage("B", 0.01)]
        before = deepcopy(candidates)
        with patch("app.reranking.score_pairs", return_value=[-1.0, 4.0]) as score:
            result = rerank_passages("问题", candidates, limit=1)
        score.assert_called_once_with("问题", ["练习标题\n正文A", "练习标题\n正文B"])
        self.assertEqual(result[0]["chunk_id"], "B")
        self.assertEqual(result[0]["content"], "正文B")
        self.assertEqual(result[0]["rerank_details"]["input_rank"], 2)
        self.assertEqual(result[0]["rerank_details"]["input_score"], 0.01)
        self.assertEqual(result[0]["retrieval"], "rerank")
        self.assertEqual(candidates, before)

    def test_no_candidates_skips_model(self):
        with patch("app.reranking.score_pairs") as scorer:
            self.assertEqual(rerank_passages("未收录问题", [], limit=3), [])
        scorer.assert_not_called()

    def test_count_nan_and_infinite_scores_are_rejected(self):
        for scores in ([], [math.nan], [math.inf]):
            with patch("app.reranking.score_pairs", return_value=scores):
                with self.assertRaises(AppError):
                    rerank_passages("问题", [passage("A", 1)], limit=1)

    def test_score_tie_uses_chunk_id(self):
        with patch("app.reranking.score_pairs", return_value=[1.0, 1.0]):
            result = rerank_passages("问题", [passage("B", 1), passage("A", 1)], limit=3)
        self.assertEqual([p["chunk_id"] for p in result], ["A", "B"])

    def test_router_does_not_truncate_fused_candidates_before_rerank(self):
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "rerank", "KNOWLEDGE_CANDIDATE_LIMIT": "10"}), patch("app.knowledge.search_keyword", return_value=[passage("A", 1), passage("B", 1)]), patch("app.vector_index.search_semantic", return_value=[passage("C", 0.8)]), patch("app.reranking.rerank_passages", return_value=[]) as rerank:
            search_knowledge(SearchKnowledgeArgs(query="问题", limit=1))
        self.assertEqual(len(rerank.call_args.args[1]), 3)
        self.assertEqual(rerank.call_args.kwargs, {"limit": 1})

    def test_reranker_failure_does_not_return_hybrid_result(self):
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "rerank"}), patch("app.knowledge.search_keyword", return_value=[passage("A", 1)]), patch("app.vector_index.search_semantic", return_value=[]), patch("app.reranking.score_pairs", side_effect=AppError("controlled")):
            with self.assertRaises(AppError):
                search_knowledge(SearchKnowledgeArgs(query="问题"))

    def test_online_model_loading_uses_local_files_only(self):
        get_reranker.cache_clear()
        self.addCleanup(get_reranker.cache_clear)
        with patch("fastembed.rerank.cross_encoder.TextCrossEncoder") as constructor:
            get_reranker("test-model", False)
        self.assertTrue(constructor.call_args.kwargs["local_files_only"])
        self.assertEqual(constructor.call_args.kwargs["providers"], ["CPUExecutionProvider"])

    def test_score_adapter_preserves_query_document_pairing_and_rejects_bad_count(self):
        model = Mock()
        model.rerank.return_value = [2.5, -3.0]
        with patch("app.reranking.get_reranker", return_value=model):
            self.assertEqual(score_pairs("问题", ["正文A", "正文B"]), [2.5, -3.0])
            model.rerank.assert_called_once_with("问题", ["正文A", "正文B"], batch_size=4)
            model.rerank.return_value = []
            with self.assertRaises(AppError):
                score_pairs("问题", ["正文A"])


if __name__ == "__main__":
    unittest.main()
