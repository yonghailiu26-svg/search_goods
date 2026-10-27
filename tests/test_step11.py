from copy import deepcopy
import unittest
from unittest.mock import patch

from app.config import AppError
from app.hybrid_search import fuse_rankings
from app.knowledge import search_knowledge
from app.schemas import SearchKnowledgeArgs


def passage(chunk_id, score):
    return {"chunk_id": chunk_id, "source_id": "KB-TEST-001", "source": "knowledge/KB-TEST-001.md",
            "source_version": "test-version", "start_line": 4, "end_line": 8, "content": "练习正文", "score": score}


class Step11Tests(unittest.TestCase):
    def test_consensus_candidate_beats_single_route_first_places(self):
        keyword = [passage("A", 100), passage("B", 1)]
        semantic = [passage("C", 0.99), passage("B", 0.61)]
        result = fuse_rankings(keyword, semantic, limit=3)
        self.assertEqual([row["chunk_id"] for row in result], ["B", "A", "C"])
        self.assertAlmostEqual(result[0]["score"], 1 / 62 + 1 / 62, places=8)

    def test_original_score_scales_do_not_change_fusion(self):
        keyword = [passage("A", 100), passage("B", 1)]
        semantic = [passage("B", 0.9), passage("A", 0.8)]
        first = fuse_rankings(keyword, semantic, limit=3)
        keyword[0]["score"] = 10000
        semantic[0]["score"] = 0.91
        second = fuse_rankings(keyword, semantic, limit=3)
        self.assertEqual([(r["chunk_id"], r["score"]) for r in first], [(r["chunk_id"], r["score"]) for r in second])

    def test_duplicate_ids_count_once_per_route_and_keep_explanation(self):
        keyword = [passage("A", 2), passage("A", 2)]
        semantic = [passage("A", 0.8)]
        result = fuse_rankings(keyword, semantic, limit=3)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["retrieval_details"]), 2)
        self.assertAlmostEqual(result[0]["score"], 2 / 61, places=8)
        self.assertEqual(result[0]["retrieval"], "hybrid")
        self.assertEqual(result[0]["score_kind"], "rrf")

    def test_empty_routes_and_one_route_do_not_invent_passages(self):
        self.assertEqual(fuse_rankings([], [], limit=3), [])
        for keyword, semantic in (([passage("B", 2), passage("A", 1)], []), ([], [passage("B", 0.9), passage("A", 0.7)])):
            self.assertEqual([p["chunk_id"] for p in fuse_rankings(keyword, semantic, limit=1)], ["B"])

    def test_preserves_body_metadata_and_does_not_mutate_input(self):
        keyword = [passage("A", 2)]
        keyword[0]["matched_keywords"] = ["包装"]
        before = deepcopy(keyword)
        output = fuse_rankings(keyword, [], limit=1)[0]
        self.assertEqual(keyword, before)
        for field in ("content", "source", "source_version", "start_line", "end_line"):
            self.assertEqual(output[field], keyword[0][field])
        self.assertEqual(output["retrieval_details"][0]["matched_keywords"], ["包装"])

    def test_router_uses_larger_candidate_window_before_final_limit(self):
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "hybrid", "KNOWLEDGE_CANDIDATE_LIMIT": "10"}), patch("app.knowledge.search_keyword", return_value=[passage("A", 2), passage("B", 1)]) as keyword, patch("app.vector_index.search_semantic", return_value=[passage("C", 0.9), passage("B", 0.8)]) as semantic:
            output = search_knowledge(SearchKnowledgeArgs(query="练习", limit=1))
        self.assertEqual([p["chunk_id"] for p in output], ["B"])
        self.assertEqual(keyword.call_args.kwargs, {"candidate_limit": 10})
        self.assertEqual(semantic.call_args.kwargs, {"candidate_limit": 10})

    def test_semantic_failure_is_not_disguised_as_successful_keyword_only(self):
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "hybrid"}), patch("app.knowledge.search_keyword", return_value=[passage("A", 1)]), patch("app.vector_index.search_semantic", side_effect=AppError("controlled failure")):
            with self.assertRaises(AppError):
                search_knowledge(SearchKnowledgeArgs(query="包装"))

    def test_candidate_window_and_strategy_configuration_are_validated(self):
        for value in ("2", "51", "not-number"):
            with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "hybrid", "KNOWLEDGE_CANDIDATE_LIMIT": value}):
                with self.assertRaises(AppError):
                    search_knowledge(SearchKnowledgeArgs(query="包装"))
        with patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "unknown"}):
            with self.assertRaises(AppError):
                search_knowledge(SearchKnowledgeArgs(query="包装"))


if __name__ == "__main__":
    unittest.main()
