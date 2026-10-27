from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Path as PathParam

from app.agent import run_agent
from app.config import AppError
from app.schemas import ChatRequest, GetProductDetailArgs
from app.workflows import run_package_check
from app.sessions import store
from app.session_repository import load_session

app = FastAPI(title="找商品 Agent · 第十五课", description="Agent、RAG与工作流学习项目；本机练习用途。")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", include_in_schema=False)
def chat_page():
    return FileResponse(WEB_DIR / "index.html")


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # 不把用户原始输入放入校验错误响应。
    detail = "请检查sku格式和额外字段。" if request.url.path.startswith("/workflows/") else "请检查message文本（1到1000字）、session_id格式和额外字段。"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/health")
def health():
    return {"status": "ok", "step": 15}


@app.post("/workflows/package-check")
def package_check(body: GetProductDetailArgs):
    try:
        return run_package_check(body)
    except AppError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc), "error_code": exc.code, "diagnostics": exc.diagnostics})


@app.get("/sessions/{session_id}")
def read_session(session_id: str = PathParam(pattern=r"^[a-f0-9]{32}$")):
    try:
        saved = load_session(session_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        return saved
    except AppError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.post("/chat")
def chat(body: ChatRequest):
    # 使用同步 def，让 FastAPI 在线程池运行阻塞的 httpx / PyMySQL 调用。
    try:
        try:
            session_id, session = store.get_or_create(body.session_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="会话不存在；不传session_id可开始新会话。") from None
        # 同一会话串行更新，避免两个并发请求互相覆盖状态。
        with session.lock:
            try:
                try:
                    store.reload(session_id, session)
                except KeyError:
                    store.discard(session_id)
                    raise HTTPException(status_code=404, detail="会话不存在。") from None
                result = run_agent(
                    body.message, current_requirements=session.requirements, history=session.history,
                )
            except AppError:
                if body.session_id is None:
                    store.discard(session_id)
                raise
            # 模型与SQL全部成功后，才一次性保存本轮条件和对话。
            try:
                store.save(session_id, session, result, body.message)
            except AppError as exc:
                exc.code = "session_save_failed"
                exc.diagnostics = {name: result[name] for name in ("usage", "model_trace", "tool_trace", "usage_complete", "elapsed_seconds") if name in result}
                raise
        return {"session_id": session_id, **result}
    except AppError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc), "error_code": exc.code, "diagnostics": exc.diagnostics})
