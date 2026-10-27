"""会话持久化：条件与本轮文字消息一致提交，不在模型请求期间持有事务。"""
import json
from pathlib import Path
import re
from uuid import uuid4

import pymysql
from pydantic import ValidationError

from app.config import AppError
from app.schemas import SearchProductsArgs
from app.storage import connect


def initialize_tables() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "04-session-tables.sql"
    # 本文件只有两条受项目控制的建表语句，不接受用户SQL。
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                for statement in sql_path.read_text(encoding="utf-8").split(";"):
                    if statement.strip():
                        cursor.execute(statement)
    except pymysql.MySQLError:
        raise AppError("会话建表失败，请检查MySQL权限及是否有同名不兼容表。") from None


def check_id(session_id: str) -> None:
    if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
        raise AppError("会话ID必须是32位小写十六进制字符。")


def create_session() -> str:
    session_id = uuid4().hex
    try:
        with connect() as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO sessions (session_id, requirements) VALUES (%s, %s)", (session_id, "{}"))
                connection.commit()
            except pymysql.MySQLError:
                connection.rollback()
                raise
    except pymysql.MySQLError:
        raise AppError("创建会话失败，请确认会话表已初始化。") from None
    return session_id


def save_round(session_id: str, requirements: dict, user_message: str, assistant_message: str) -> None:
    check_id(session_id)
    try:
        args = SearchProductsArgs.model_validate(requirements)
    except ValidationError:
        raise AppError("需求条件校验失败，本轮没有写入数据库。") from None
    for text in (user_message, assistant_message):
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 60000:
            raise AppError("消息必须是非空文本，且UTF-8长度不超过60000字节。")
    encoded = json.dumps(args.model_dump(exclude_none=True, exclude_unset=True), ensure_ascii=False)
    try:
        with connect() as connection:
            try:
                with connection.cursor() as cursor:
                    # 锁仅覆盖这段短数据库事务，不覆盖模型请求。
                    cursor.execute("SELECT session_id FROM sessions WHERE session_id = %s FOR UPDATE", (session_id,))
                    if not cursor.fetchone():
                        raise AppError("会话不存在，不能保存本轮消息。")
                    cursor.execute("UPDATE sessions SET requirements = %s WHERE session_id = %s", (encoded, session_id))
                    cursor.executemany(
                        "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                        [(session_id, "user", user_message), (session_id, "assistant", assistant_message)],
                    )
                connection.commit()  # 条件与两条消息一起提交。
            except (pymysql.MySQLError, AppError):
                connection.rollback()  # 中途失败，一起撤销。
                raise
    except pymysql.MySQLError:
        raise AppError("保存会话失败，本轮条件与消息已回滚。") from None


def load_session(session_id: str) -> dict | None:
    check_id(session_id)
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT requirements FROM sessions WHERE session_id = %s FOR UPDATE", (session_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                requirements = json.loads(row["requirements"])
                SearchProductsArgs.model_validate(requirements)
                cursor.execute(
                    "SELECT role, content FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT 12", (session_id,),
                )
                history = list(reversed(cursor.fetchall()))
                return {"session_id": session_id, "requirements": requirements, "history": history}
    except pymysql.MySQLError:
        raise AppError("读取会话失败，请检查MySQL及会话表。") from None
    except (ValueError, TypeError, ValidationError):
        raise AppError("数据库中的会话条件格式不正确。") from None
