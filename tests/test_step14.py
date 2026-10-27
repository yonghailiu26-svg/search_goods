import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.config import AppError
from app.evaluation import aggregate_scores, load_cases, quality_checks, score_case, write_report
from app.knowledge_index import PROJECT_ROOT


class Step14Tests(unittest.TestCase):
    def test_metrics_for_second_place_relevant_document(self):
        result = score_case(["A", "B"], ["B"], k=3)
        self.assertEqual(result, {"hit_at_k": 1, "precision_at_k": 0.5, "recall_at_k": 1.0, "mrr_at_k": 0.5, "abstained": None})

    def test_miss_and_partial_recall(self):
        missing = score_case([], ["B"])
        self.assertEqual(missing["hit_at_k"], 0)
        self.assertEqual(missing["mrr_at_k"], 0)
        partial = score_case(["B", "C"], ["B", "D"])
        self.assertEqual(partial["recall_at_k"], 0.5)

    def test_cutoff_is_applied_before_grading(self):
        self.assertEqual(score_case(["A", "B", "C", "D"], ["D"], k=3)["hit_at_k"], 0)

    def test_negative_examples_are_not_counted_as_positive_hits(self):
        empty, nonempty = score_case([], []), score_case(["A"], [])
        self.assertIsNone(empty["hit_at_k"])
        self.assertTrue(empty["abstained"])
        self.assertFalse(nonempty["abstained"])
        summary = aggregate_scores([score_case(["A"], ["A"]), empty, nonempty])
        self.assertEqual(summary["hit_at_k"], 1)
        self.assertEqual(summary["abstention_rate"], 0.5)
        self.assertEqual(summary["answerable_count"], 1)

    def test_duplicates_and_invalid_cutoff_do_not_inflate_metrics(self):
        for predicted, expected, k in ((["A", "A"], ["A"], 3), (["A"], ["A", "A"], 3), (["A"], ["A"], 0)):
            with self.assertRaises(ValueError):
                score_case(predicted, expected, k=k)

    def test_empty_aggregate_is_unknown_not_perfect(self):
        summary = aggregate_scores([])
        self.assertIsNone(summary["hit_at_k"])
        self.assertFalse(all(quality_checks(summary).values()))

    def test_minimum_and_baseline_regression_checks(self):
        passing = {"hit_at_k": 1, "mrr_at_k": 1, "abstention_rate": 1, "recall_at_k": 1, "precision_at_k": 0.5}
        self.assertTrue(all(quality_checks(passing, baseline=passing).values()))
        worse = {**passing, "mrr_at_k": 0.8}
        checks = quality_checks(worse, baseline=passing)
        self.assertTrue(checks["minimum_mrr_at_k"])
        self.assertFalse(checks["baseline_mrr_at_k"])

    def test_dataset_requires_valid_unique_labels_and_positive_negative_cases(self):
        work = PROJECT_ROOT / "work"
        work.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=work) as directory:
            path = Path(directory) / "cases.json"
            valid = {"version": 1, "cases": [{"id": "p", "query": "问题", "relevant_chunk_ids": ["A"]}, {"id": "n", "query": "无资料", "relevant_chunk_ids": []}]}
            path.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(len(load_cases(path, {"A"}).cases), 2)
            for variant in ({**valid, "version": 2}, {"version": 1, "cases": [valid["cases"][0]]}, {"version": 1, "cases": [valid["cases"][0], valid["cases"][0]]}):
                path.write_text(json.dumps(variant), encoding="utf-8")
                with self.assertRaises(AppError):
                    load_cases(path, {"A"})
            path.write_text(json.dumps(valid), encoding="utf-8")
            with self.assertRaises(AppError):
                load_cases(path, {"B"})

    def test_report_roundtrip_and_no_temporary_file_left(self):
        with TemporaryDirectory(dir=PROJECT_ROOT / "work") as directory:
            path = Path(directory) / "report.json"
            write_report(path, {"passed": False, "reason": "测试失败样例"})
            self.assertFalse(json.loads(path.read_text(encoding="utf-8"))["passed"])
            self.assertFalse(path.with_name("report.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
