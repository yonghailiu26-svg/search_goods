from copy import deepcopy
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.config import AppError
from app.embeddings import normalize
from app.knowledge import search_knowledge
from app.knowledge_index import PROJECT_ROOT, build_index
from app.schemas import SearchKnowledgeArgs
from app.vector_index import build_vectors, corpus_hash, load_vectors, minimum_score, search_semantic, write_vectors


class Step10Tests(unittest.TestCase):
    def setUp(self):
        work = PROJECT_ROOT / "work"
        work.mkdir(exist_ok=True)
        temporary = TemporaryDirectory(dir=work)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "vectors.json"
        self.corpus = build_index()
        environment = patch.dict("os.environ", {"EMBEDDING_MODEL": "test-model", "KNOWLEDGE_MIN_SCORE": "0.58", "KNOWLEDGE_RETRIEVAL": "semantic"})
        environment.start()
        self.addCleanup(environment.stop)
        # 两维向量只是可计算的测试夹具，真实模型验证在verify_step10.py。
        vectors = [[0.0, 1.0] for _ in self.corpus.chunks]
        vectors[0] = [1.0, 0.0]
        vectors[1] = [0.6, 0.8]
        with patch("app.vector_index.embed_documents", return_value=vectors):
            self.index = build_vectors(self.corpus)
        write_vectors(self.index, self.path)

    def test_normalization_and_invalid_vectors(self):
        self.assertEqual(normalize([3, 4]), [0.6, 0.8])
        for values in ([], [0, 0], [math.nan, 1], [math.inf, 1]):
            with self.assertRaises(AppError):
                normalize(values)

    def test_rank_threshold_and_limit_use_cosine_not_keywords(self):
        with patch("app.vector_index.load_vectors", return_value=self.index), patch("app.vector_index.embed_query", return_value=[1.0, 0.0]):
            result = search_semantic(SearchKnowledgeArgs(query="完全不含作者关键词", limit=2), self.corpus)
        self.assertEqual([row["score"] for row in result], [1.0, 0.6])
        self.assertEqual([row["chunk_id"] for row in result], [self.corpus.chunks[0].chunk_id, self.corpus.chunks[1].chunk_id])
        self.assertEqual(result[0]["retrieval"], "semantic")
        self.assertEqual(result[0]["content"], self.corpus.chunks[0].content)

    def test_no_score_above_threshold_returns_empty_without_forced_top_one(self):
        with patch("app.vector_index.load_vectors", return_value=self.index), patch("app.vector_index.embed_query", return_value=[-1.0, 0.0]):
            self.assertEqual(search_semantic(SearchKnowledgeArgs(query="不相关"), self.corpus), [])

    def test_model_recipe_corpus_and_dimension_mismatch_are_rejected(self):
        for key, value in (("model_name", "other-model"), ("recipe", "wrong-recipe"), ("corpus_hash", "wrong-hash"), ("dimension", 3)):
            broken = self.index.model_copy(update={key: value})
            write_vectors(broken, self.path)
            with self.assertRaises(AppError):
                load_vectors(self.corpus, self.path)
        changed = deepcopy(self.corpus)
        changed.chunks[0].content += "更新"
        self.assertNotEqual(corpus_hash(changed), corpus_hash(self.corpus))
        changed = self.corpus.model_copy(update={"built_at": "different-time"})
        self.assertEqual(corpus_hash(changed), corpus_hash(self.corpus))

    def test_missing_duplicate_nonunit_and_nan_vectors_are_rejected(self):
        variants = []
        missing = self.index.model_dump()
        missing["vectors"].pop()
        variants.append(missing)
        duplicate = self.index.model_dump()
        duplicate["vectors"].append(duplicate["vectors"][0])
        variants.append(duplicate)
        for values in ([0.0, 0.0], [2.0, 0.0], [math.nan, 0.0]):
            bad = self.index.model_dump()
            bad["vectors"][0]["values"] = values
            variants.append(bad)
        for variant in variants:
            self.path.write_text(json.dumps(variant), encoding="utf-8")
            with self.assertRaises(AppError):
                load_vectors(self.corpus, self.path)

    def test_query_dimension_and_invalid_threshold_fail_before_ranking(self):
        with patch("app.vector_index.load_vectors", return_value=self.index), patch("app.vector_index.embed_query", return_value=[1.0]):
            with self.assertRaises(AppError):
                search_semantic(SearchKnowledgeArgs(query="包装"), self.corpus)
        for value in ("nan", "inf", "-0.1", "1.1", "not-a-number"):
            with patch.dict("os.environ", {"KNOWLEDGE_MIN_SCORE": value}):
                with self.assertRaises(AppError):
                    minimum_score()

    def test_semantic_failure_never_silently_falls_back_to_keyword(self):
        with patch("app.vector_index.search_semantic", side_effect=AppError("controlled failure")), patch("app.knowledge.search_keyword") as keyword:
            with self.assertRaises(AppError):
                search_knowledge(SearchKnowledgeArgs(query="包装"))
        keyword.assert_not_called()

    def test_failed_embedding_build_keeps_previous_vector_file(self):
        before = self.path.read_bytes()
        with patch("app.vector_index.embed_documents", side_effect=AppError("controlled failure")):
            with self.assertRaises(AppError):
                write_vectors(build_vectors(self.corpus), self.path)
        self.assertEqual(before, self.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
