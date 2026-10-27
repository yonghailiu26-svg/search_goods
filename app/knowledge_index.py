"""第八课：离线分块与索引；不请求模型、不连接数据库。"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import AppError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
INDEX_PATH = PROJECT_ROOT / "outputs" / "knowledge-index.json"
CHUNKER_VERSION = "paragraph-v1"
DEFAULT_MAX_CHARS = 260


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str
    source: str
    source_version: str


class ChunkRecord(SourceRecord):
    chunk_id: str
    title: str
    section: str
    content: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    keywords: list[str]


class KnowledgeIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int
    chunker_version: str
    max_chars: int = Field(ge=80, le=2000)
    built_at: str
    sources: list[SourceRecord] = Field(min_length=1)
    chunks: list[ChunkRecord] = Field(min_length=1)


def read_sources(directory: Path) -> list[tuple[Path, str, str]]:
    """返回固定资料目录中的路径、归一化正文、完整原文件内容哈希。"""
    try:
        paths = sorted(directory.glob("KB-*.md"))
        if not paths:
            raise AppError("没有规则文件，请检查knowledge目录。", code="knowledge_unavailable")
        records = []
        for path in paths:
            if not re.fullmatch(r"KB-[A-Z0-9-]+", path.stem):
                raise AppError("规则文件名必须使用KB-开头的大写字母、数字或连字符。", code="knowledge_unavailable")
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            records.append((path, text, sha256(raw).hexdigest()))
        return records
    except (OSError, UnicodeError):
        raise AppError("规则资料读取失败。", code="knowledge_unavailable") from None


def trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def paragraph_spans(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """优先保持段落；超长段落退到中文句子，超长单句最后才按字符切。"""
    boundaries = [start]
    for match in re.finditer(r"\n[ \t]*\n", text[start:end]):
        boundaries.extend((start + match.start(), start + match.end()))
    boundaries.append(end)
    atoms = []
    for left, right in zip(boundaries[::2], boundaries[1::2]):
        left, right = trim_span(text, left, right)
        if left == right:
            continue
        if right - left <= max_chars:
            atoms.append((left, right))
            continue
        sentence_start = left
        cuts = [left + match.end() for match in re.finditer(r"[。！？；]", text[left:right])]
        if not cuts or cuts[-1] != right:
            cuts.append(right)
        for sentence_end in cuts:
            while sentence_end - sentence_start > max_chars:
                atoms.append((sentence_start, sentence_start + max_chars))
                sentence_start += max_chars
            part_start, part_end = trim_span(text, sentence_start, sentence_end)
            if part_start < part_end:
                atoms.append((part_start, part_end))
            sentence_start = sentence_end
    return atoms


def chunk_document(path: Path, text: str, version: str, max_chars: int) -> list[ChunkRecord]:
    lines = text.splitlines(keepends=True)
    if len(lines) < 3 or not lines[0].startswith("# ") or not lines[1].startswith("关键词："):
        raise AppError("规则格式不正确，需要标题、关键词行和正文。", code="knowledge_unavailable")
    title = lines[0][2:].strip()
    keywords = [word.strip() for word in lines[1].strip().removeprefix("关键词：").split("、") if word.strip()]
    body_start = len(lines[0]) + len(lines[1])
    if not title or not keywords or not text[body_start:].strip():
        raise AppError("规则标题、关键词或正文为空。", code="knowledge_unavailable")
    headings = []
    offset = body_start
    for line in lines[2:]:
        if line.startswith("## "):
            headings.append((offset, line[3:].strip()))
        offset += len(line)
    # 首个小标题前的简介和首节放在一起，避免把声明切成孤立片段。
    sections = [(body_start, headings[0][1] if headings else "")]
    sections.extend(headings[1:])
    chunks = []
    for index, (section_start, section) in enumerate(sections):
        section_end = sections[index + 1][0] if index + 1 < len(sections) else len(text)
        pending = None
        spans = []
        for start, end in paragraph_spans(text, section_start, section_end, max_chars):
            if pending is not None and end - pending[0] > max_chars:
                spans.append(pending)
                pending = None
            pending = (pending[0], end) if pending is not None else (start, end)
        if pending is not None:
            spans.append(pending)
        for start, end in spans:
            content = text[start:end]
            keyword_text = (section + "\n" + content).casefold()
            local_keywords = sorted({word for word in keywords if word.casefold() in keyword_text})
            chunks.append(ChunkRecord(
                chunk_id=f"{path.stem}-C{len(chunks) + 1:03d}", source_id=path.stem,
                title=title, section=section, source=path.relative_to(PROJECT_ROOT).as_posix(),
                source_version=version, content=content, keywords=local_keywords,
                start_line=text.count("\n", 0, start) + 1,
                end_line=text.count("\n", 0, end - 1) + 1,
            ))
    return chunks


def build_index(directory: Path = KNOWLEDGE_DIR, *, max_chars: int = DEFAULT_MAX_CHARS) -> KnowledgeIndex:
    if type(max_chars) is not int or not 80 <= max_chars <= 2000:
        raise AppError("分块字符上限必须是80到2000的整数。", code="knowledge_unavailable")
    sources, chunks = [], []
    for path, text, version in read_sources(directory):
        sources.append(SourceRecord(source_id=path.stem, source=path.relative_to(PROJECT_ROOT).as_posix(), source_version=version))
        chunks.extend(chunk_document(path, text, version, max_chars))
    return KnowledgeIndex(
        schema_version=1, chunker_version=CHUNKER_VERSION, max_chars=max_chars,
        built_at=datetime.now(timezone(timedelta(hours=8))).isoformat(), sources=sources, chunks=chunks,
    )


def write_index(index: KnowledgeIndex, output: Path = INDEX_PATH) -> None:
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(index.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(output)  # 完整写好后再替换，构建失败不会先清空旧索引。
    except OSError:
        raise AppError("写入知识索引失败。", code="knowledge_unavailable") from None


def load_index(directory: Path = KNOWLEDGE_DIR, index_path: Path = INDEX_PATH) -> KnowledgeIndex:
    records = read_sources(directory)
    current = {path.relative_to(PROJECT_ROOT).as_posix(): version for path, _, version in records}
    try:
        index = KnowledgeIndex.model_validate_json(index_path.read_text(encoding="utf-8"))
        saved = {source.source: source.source_version for source in index.sources}
        if index.schema_version != 1 or index.chunker_version != CHUNKER_VERSION or saved != current:
            raise AppError("知识索引已过期，请运行build_knowledge_index.py重新构建。", code="knowledge_unavailable")
        seen = set()
        for chunk in index.chunks:
            if (chunk.chunk_id in seen or chunk.start_line > chunk.end_line or
                    len(chunk.content) > index.max_chars or current.get(chunk.source) != chunk.source_version):
                raise ValueError
            seen.add(chunk.chunk_id)
        return index
    except (OSError, UnicodeError, ValueError, ValidationError):
        raise AppError("知识索引缺失或损坏，请运行build_knowledge_index.py。", code="knowledge_unavailable") from None
