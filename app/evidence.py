"""第九课：混合回答的证据清单、结论引用校验与文本展示，不调用模型或数据库。"""
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import AppError


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)


class EvidenceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    claims: list[EvidenceClaim] = Field(max_length=6)
    unknowns: list[str] = Field(max_length=4)


def collect_sources(trace: list[dict]) -> list[dict]:
    sources = {}
    for row in trace:
        if row["tool"] != "search_knowledge":
            continue
        for passage in row.get("passages", []):
            citation_id = passage.get("chunk_id", passage["source_id"])
            source = {key: passage[key] for key in (
                "source_id", "title", "source", "chunk_id", "section", "start_line", "end_line", "source_version",
            ) if key in passage}
            source["citation_id"] = citation_id
            sources[citation_id] = source
    return list(sources.values())


def collect_evidence(trace: list[dict]) -> dict | None:
    """只有本轮实际尝试过规则检索和商品详情，才开启混合回答契约。"""
    observations = [row for row in trace if row["status"] != "invalid_arguments"]
    tools = {row["tool"] for row in observations}
    if not {"search_knowledge", "get_product_detail"} <= tools:
        return None
    items, gaps = {}, []
    for row in observations:
        if row["tool"] == "search_knowledge":
            for passage in row.get("passages", []):
                evidence_id = passage.get("chunk_id", passage["source_id"])
                items[evidence_id] = {"id": evidence_id, "kind": "rule"}
            if row["status"] == "no_knowledge":
                gaps.append("本轮有规则检索未命中资料，不能把未命中解释为相关规则不存在。")
        elif row["tool"] == "get_product_detail":
            product = row.get("product")
            if product is None:
                gaps.append(f"本轮未查到SKU {row['arguments']['sku']}，不能描述其商品详情。")
            else:
                evidence_id = f"SKU:{product['sku']}"
                items[evidence_id] = {"id": evidence_id, "kind": "product", "sku": product["sku"]}
                if not product.get("package_notes"):
                    gaps.append(f"SKU {product['sku']}未提供包装说明，无法据此确定盒装数量。")
    return {"items": list(items.values()), "gaps": list(dict.fromkeys(gaps))}


def validate_evidence_answer(content: str, context: dict) -> EvidenceAnswer:
    try:
        answer = EvidenceAnswer.model_validate_json(content)
        available = {item["id"]: item["kind"] for item in context["items"]}
        used = set()
        for claim in answer.claims:
            refs = set(claim.evidence_ids)
            if refs - available.keys():
                raise ValueError
            used.update(refs)
        # 既然查询了两类且都有依据，不能只总结其中一类。
        if {available[ref] for ref in used} != set(available.values()):
            raise ValueError
        if any(not text.strip() or len(text) > 400 for text in answer.unknowns):
            raise ValueError
        if not answer.claims and not answer.unknowns and not context["gaps"]:
            raise ValueError
        return answer
    except (ValueError, ValidationError):
        raise AppError("混合回答格式无效、遗漏已有证据类型或引用了本轮未取得的依据，本次已停止。", code="invalid_evidence") from None


def render_evidence_answer(answer: EvidenceAnswer, context: dict) -> tuple[str, dict]:
    """保留结构供检查；确定缺口由Python补入，不能由模型省略。"""
    unknowns = list(dict.fromkeys([*context["gaps"], *answer.unknowns]))
    lines = [claim.text + " " + " ".join(f"[{ref}]" for ref in dict.fromkeys(claim.evidence_ids)) for claim in answer.claims]
    if unknowns:
        lines.append("暂无法确认：\n" + "\n".join(f"- {text}" for text in unknowns))
    details = {"claims": [claim.model_dump() for claim in answer.claims], "unknowns": unknowns}
    return "\n\n".join(lines), details
