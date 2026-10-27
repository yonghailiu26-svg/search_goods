import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.agent import run_agent
from app.config import AppError
from app.knowledge import search_knowledge
from app.knowledge_index import PROJECT_ROOT, build_index, load_index, write_index
from app.schemas import SearchKnowledgeArgs
from app.tool_runner import execute_knowledge

COUNTS = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
TEXT = "# 练习规则\n关键词：包装、盒装、预算\n\n## 包装依据\n\n包装数量应查询具体SKU，不能猜测。\n\n## 预算单位\n\n预算单位为分，5元等于500分。\n"


class Step8Tests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"KNOWLEDGE_RETRIEVAL": "keyword"})
        environment.start()
        self.addCleanup(environment.stop)
        work = PROJECT_ROOT / "work"
        work.mkdir(exist_ok=True)
        temporary = TemporaryDirectory(dir=work)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "KB-TEST-001.md"
        self.path.write_text(TEXT, encoding="utf-8")
        self.output = self.directory / "index.json"

    def build(self, max_chars=80):
        index = build_index(self.directory, max_chars=max_chars)
        write_index(index, self.output)
        return index

    def test_headings_keep_unrelated_rules_separate_and_keywords_local(self):
        index = self.build()
        self.assertEqual(len(index.chunks), 2)
        package, price = index.chunks
        self.assertEqual(package.section, "包装依据")
        self.assertNotIn("500", package.content)
        self.assertEqual(package.keywords, ["包装"])
        self.assertEqual(price.keywords, ["预算"])
        with patch("app.knowledge.KNOWLEDGE_DIR", self.directory), patch("app.knowledge.INDEX_PATH", self.output):
            result = search_knowledge(SearchKnowledgeArgs(query="包装"))
        self.assertEqual([row["chunk_id"] for row in result], [package.chunk_id])

    def test_source_lines_versions_and_chunk_ids_are_reproducible(self):
        first, second = self.build(), self.build()
        self.assertEqual(first.chunks, second.chunks)
        text = self.path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for chunk in first.chunks:
            self.assertIn(chunk.content, "\n".join(lines[chunk.start_line - 1:chunk.end_line]))
            self.assertEqual(chunk.source_version, first.sources[0].source_version)
            self.assertEqual(len(chunk.source_version), 64)
            self.assertTrue((PROJECT_ROOT / chunk.source).is_file())

    def test_long_paragraphs_and_sentences_keep_all_nonspace_text_within_limit(self):
        body = "## 包装规则\n\n" + "这是完整的短句。" * 20 + "\n\n" + "长" * 213
        self.path.write_text("# 测试\n关键词：包装\n\n" + body, encoding="utf-8")
        index = self.build()
        recovered = "".join(chunk.content for chunk in index.chunks)
        self.assertEqual(re.sub(r"\s", "", recovered), re.sub(r"\s", "", body))
        self.assertGreater(len(index.chunks), 4)
        self.assertTrue(all(0 < len(chunk.content) <= 80 for chunk in index.chunks))

    def test_source_edit_rejects_stale_index_then_rebuild_uses_new_content(self):
        old = self.build()
        self.path.write_text(TEXT.replace("500分", "五百分"), encoding="utf-8")
        with self.assertRaisesRegex(AppError, "已过期"):
            load_index(self.directory, self.output)
        with patch("app.knowledge.KNOWLEDGE_DIR", self.directory), patch("app.knowledge.INDEX_PATH", self.output):
            with self.assertRaises(AppError) as caught:
                execute_knowledge('{"query":"包装"}', {}, search=search_knowledge)
        self.assertEqual(caught.exception.code, "tool_failed")
        self.assertIn("build_knowledge_index.py", str(caught.exception))
        rebuilt = self.build()
        self.assertNotEqual(old.sources[0].source_version, rebuilt.sources[0].source_version)
        self.assertEqual(load_index(self.directory, self.output).chunks, rebuilt.chunks)
        self.assertIn("五百分", rebuilt.chunks[1].content)

    def test_added_or_deleted_source_requires_rebuild(self):
        self.build()
        other = self.directory / "KB-OTHER-001.md"
        other.write_text(TEXT, encoding="utf-8")
        with self.assertRaisesRegex(AppError, "已过期"):
            load_index(self.directory, self.output)
        self.build()
        other.unlink()
        with self.assertRaisesRegex(AppError, "已过期"):
            load_index(self.directory, self.output)

    def test_missing_broken_and_duplicate_chunk_index_are_not_empty_results(self):
        with self.assertRaisesRegex(AppError, "缺失或损坏"):
            load_index(self.directory, self.output)
        self.output.write_text("not-json", encoding="utf-8")
        with self.assertRaises(AppError):
            load_index(self.directory, self.output)
        index = self.build()
        broken = index.model_dump()
        broken["chunks"].append(broken["chunks"][0])
        self.output.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(AppError, "缺失或损坏"):
            load_index(self.directory, self.output)

    def test_bad_build_does_not_overwrite_existing_index(self):
        self.build()
        before = self.output.read_bytes()
        self.path.write_text("broken source", encoding="utf-8")
        with self.assertRaises(AppError):
            write_index(build_index(self.directory), self.output)
        self.assertEqual(before, self.output.read_bytes())
        for limit in (79, 2001, True):
            with self.assertRaises(AppError):
                build_index(self.directory, max_chars=limit)

    def test_chunk_citation_metadata_reaches_answer_and_old_document_citation_is_rejected(self):
        passage = self.build().chunks[0].model_dump(exclude={"keywords"})
        call = {"content": None, "tool_calls": [{"id": "rules", "type": "function", "function": {
            "name": "search_knowledge", "arguments": '{"query":"包装"}',
        }}]}
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-placeholder", "DEEPSEEK_MODEL": "test-model", "AGENT_MAX_MODEL_CALLS": "3", "AGENT_MAX_TOOL_CALLS": "3"}):
            for citation in (passage["chunk_id"], passage["source_id"], "KB-TEST-001-C999"):
                with patch("app.agent.search_knowledge", return_value=[passage]), patch("app.agent.complete", side_effect=[
                    (call, COUNTS), ({"content": f"应按具体SKU确定。[{citation}]"}, COUNTS),
                ]):
                    if citation == passage["chunk_id"]:
                        result = run_agent("包装规则")
                        source = result["sources"][0]
                        self.assertEqual(source["citation_id"], passage["chunk_id"])
                        for name in ("start_line", "end_line", "section", "source_version"):
                            self.assertEqual(source[name], passage[name])
                    else:
                        with self.assertRaises(AppError) as caught:
                            run_agent("包装规则")
                        self.assertEqual(caught.exception.code, "invalid_citation")


if __name__ == "__main__":
    unittest.main()
