import json
import re
from time import perf_counter

import httpx

from app.config import AppError, integer, required
from app.evidence import collect_evidence, collect_sources, render_evidence_answer, validate_evidence_answer
from app.llm import complete
from app.knowledge import search_knowledge
from app.products import get_product_detail, search_products
from app.prompts import EVIDENCE_INSTRUCTION, SYSTEM
from app.tool_runner import execute_detail, execute_knowledge, execute_search
from app.tools import TOOLS


def run_agent(question: str, *, current_requirements: dict | None = None, history: list[dict] | None = None) -> dict:
    api_key = required("DEEPSEEK_API_KEY")
    model = required("DEEPSEEK_MODEL")
    max_calls = integer("AGENT_MAX_MODEL_CALLS", 3, 2, 5)
    max_tools = integer("AGENT_MAX_TOOL_CALLS", 3, 1, 10)
    timeout = integer("DEEPSEEK_TIMEOUT_SECONDS", 60, 1, 120)
    max_tokens = integer("DEEPSEEK_MAX_TOKENS", 700, 128, 2000)
    requirements = dict(current_requirements or {})
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "system", "content": "当前有效条件（JSON数据）：" + json.dumps(requirements, ensure_ascii=False)},
        *(history or []),
        {"role": "user", "content": question},
    ]
    trace = []
    sources = {}  # 仅收集本轮实际检索到的来源，历史回答中的引用不能直接当证据。
    evidence_context = None
    model_trace = []
    tool_calls = 0
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    started = perf_counter()

    # 固定工具名映射到Python执行函数；不会执行模型提供的代码。
    def run_search(arguments, current):
        return execute_search(arguments, current, search=search_products)

    def run_detail(arguments, current):
        return execute_detail(arguments, current, get_detail=get_product_detail)

    def run_knowledge(arguments, current):
        return execute_knowledge(arguments, current, search=search_knowledge)

    handlers = {"search_products": run_search, "get_product_detail": run_detail, "search_knowledge": run_knowledge}

    def attach_diagnostics(error: AppError, *, usage_complete: bool = True) -> AppError:
        error.diagnostics = {
            "usage": dict(usage), "usage_complete": usage_complete,
            "model_trace": list(model_trace), "tool_trace": list(trace),
            "elapsed_seconds": round(perf_counter() - started, 2),
        }
        return error

    with httpx.Client(timeout=timeout) as client:
        for round_index in range(max_calls):
            # 最后一次只允许总结或追问，确保不会无限循环。
            payload = {
                "model": model, "messages": messages, "tools": TOOLS,
                "tool_choice": "none" if round_index == max_calls - 1 else "auto",
                "stream": False, "thinking": {"type": "disabled"}, "max_tokens": max_tokens,
            }
            model_started = perf_counter()
            try:
                message, counts = complete(client, api_key, payload)
            except AppError as exc:
                reported_usage = (exc.diagnostics or {}).get("usage")
                if reported_usage:
                    for name in usage:
                        usage[name] += reported_usage[name]
                model_trace.append({
                    "step": round_index + 1, "status": exc.code,
                    "elapsed_seconds": round(perf_counter() - model_started, 3),
                    "usage": reported_usage,
                })
                raise attach_diagnostics(exc, usage_complete=reported_usage is not None) from None
            model_trace.append({
                "step": round_index + 1, "status": "ok", "usage": counts,
                "elapsed_seconds": round(perf_counter() - model_started, 3),
            })
            active_tool = None
            active_tool_name = None
            try:
                for name in usage:
                    usage[name] += counts[name]
                calls = message.get("tool_calls")
                if calls is None:
                    calls = []
                if not isinstance(calls, list):
                    raise ValueError
                if not calls:
                    answer = message.get("content")
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError
                    answer_details = None
                    if evidence_context is not None and trace[-1]["status"] != "invalid_arguments":
                        structured = validate_evidence_answer(answer, evidence_context)
                        answer, answer_details = render_evidence_answer(structured, evidence_context)
                    if trace and trace[-1]["status"] == "invalid_arguments":
                        # 未成功执行最后一次查询，不能把模型总结当作查到商品。
                        answer = "本轮工具参数尚未校验通过，请明确商品需求、SKU或要查询的规则问题后再试。"
                        outcome = "needs_clarification"
                    elif trace and all(item["tool"] == "search_knowledge" for item in trace) and not sources:
                        answer = "本地练习规则库未检索到相关资料，无法按本项目规则确认。请补充相应规则或提供更明确的问题。"
                        outcome = "no_knowledge"
                    elif trace:
                        outcome = trace[-1]["status"] if trace[-1]["status"] in ("no_results", "not_found") else "answered"
                    else:
                        outcome = "reply"
                    if outcome not in ("needs_clarification", "no_knowledge"):
                        citations = set(re.findall(r"\[(KB-[A-Z0-9-]+)\]", answer))
                        if citations - sources.keys() or (sources and not citations):
                            raise AppError("规则回答缺少有效来源或引用了本轮未检索到的资料，本次已停止。", code="invalid_citation")
                    return {
                        "answer": answer.replace(api_key, "[REDACTED]"),
                        "tool_trace": trace, "usage": usage,
                        "model_calls": round_index + 1,
                        "elapsed_seconds": round(perf_counter() - started, 2),
                        "current_requirements": requirements,
                        "model_trace": model_trace, "usage_complete": True,
                        "outcome": outcome,
                        "sources": list(sources.values()),
                        "answer_details": answer_details,
                        "execution_mode": "agent",
                        "recovered": any(item["status"] == "invalid_arguments" for item in trace) and outcome in ("answered", "no_results", "not_found", "no_knowledge"),
                    }
                if not isinstance(calls, list) or len(calls) > 3 or round_index == max_calls - 1:
                    raise AppError("模型工具调用超出执行边界，本次已停止。", code="execution_limit")
                if tool_calls + len(calls) > max_tools:
                    raise AppError("本轮工具调用次数达到上限，本次已停止。", code="execution_limit")
                tool_calls += len(calls)  # 校验失败也消耗一次调用额度，不能无限修正。
                messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
                for call in calls:
                    function = call["function"]
                    if function["name"] not in handlers:
                        raise AppError("模型请求了未授权工具，本次已停止。", code="unknown_tool")
                    if not isinstance(call["id"], str) or not call["id"]:
                        raise ValueError
                    # arguments 是 JSON 字符串，不是可以直接执行的 Python 代码。
                    active_tool = perf_counter()
                    active_tool_name = function["name"]
                    result, requirements, tool_record = handlers[active_tool_name](function["arguments"], requirements)
                    trace.append(tool_record)
                    if active_tool_name == "search_knowledge":
                        for source in collect_sources([tool_record]):
                            sources[source["citation_id"]] = source
                    active_tool = None
                    messages.append({
                        "role": "tool", "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
                updated_context = collect_evidence(trace)
                if updated_context is not None and updated_context != evidence_context:
                    evidence_context = updated_context
                    messages.append({"role": "system", "content": EVIDENCE_INSTRUCTION + "\n" + json.dumps(evidence_context, ensure_ascii=False)})
            except AppError as exc:
                if active_tool is not None:
                    trace.append({"tool": active_tool_name, "status": exc.code,
                                  "elapsed_seconds": round(perf_counter() - active_tool, 3)})
                raise attach_diagnostics(exc) from None
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise attach_diagnostics(AppError("模型响应格式异常，本次已停止。", code="invalid_response")) from None
    raise attach_diagnostics(AppError("模型请求次数已达到上限。", code="execution_limit"))
