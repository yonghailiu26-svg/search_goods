"""条件合并与进程内会话锁；生产流程以MySQL数据为准。"""
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from app.config import AppError
from app.schemas import SearchProductsArgs
from app import session_repository


def merge_requirements(current: dict, patch: SearchProductsArgs) -> SearchProductsArgs:
    # 关键：只取模型实际传来的字段，不能拿默认 None 覆盖旧条件。
    changes = patch.model_dump(exclude_unset=True)
    merged = dict(current)  # 复制旧状态，当前请求失败时不能改坏它。
    if changes.get("category") is not None and changes["category"] != current.get("category"):
        for name in ("keyword", "brand", "color", "spec"):
            merged.pop(name, None)
    merged.update(changes)  # 只覆盖本轮明确传入的字段，null表示取消。
    return SearchProductsArgs.model_validate(merged)


@dataclass
class Session:
    requirements: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)


class SessionStore:
    def __init__(self, repository=None):
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()
        self.repository = repository  # 不传时是离线测试用的内存实现。

    def get_or_create(self, session_id: str | None) -> tuple[str, Session]:
        with self._lock:
            if session_id is not None:
                if session_id not in self._sessions:
                    if self.repository is None or self.repository.load_session(session_id) is None:
                        raise KeyError(session_id)
                    if len(self._sessions) >= 100:
                        raise AppError("本课进程内活跃会话已达100个，请重启服务释放；已存会话仍在数据库。")
                    self._sessions[session_id] = Session()
                return session_id, self._sessions[session_id]
            if len(self._sessions) >= 100:
                raise AppError("本课进程内活跃会话已达100个，请重启服务释放；已存会话仍在数据库。")
            session_id = self.repository.create_session() if self.repository else uuid4().hex
            session = Session()
            self._sessions[session_id] = session
            return session_id, session

    def reload(self, session_id: str, session: Session) -> None:
        """取得同会话锁后再读库，避免等待锁时拿到过期条件。"""
        if self.repository is not None:
            saved = self.repository.load_session(session_id)
            if saved is None:
                raise KeyError(session_id)
            session.requirements = saved["requirements"]
            session.history = saved["history"]

    def save(self, session_id: str, session: Session, result: dict, question: str) -> None:
        # 先持久化，再更新本地副本；数据库保存失败时不假装本轮成功。
        if self.repository is not None:
            self.repository.save_round(session_id, result["current_requirements"], question, result["answer"])
        session.requirements = dict(result["current_requirements"])
        session.history = [*session.history,
            {"role": "user", "content": question},
            {"role": "assistant", "content": result["answer"]},
        ][-12:]

    def discard(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


store = SessionStore(repository=session_repository)
