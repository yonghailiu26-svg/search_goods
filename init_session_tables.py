"""手动运行才创建会话表，不修改已有商品数据。"""
import sys

from app.config import AppError
from app.session_repository import initialize_tables

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        initialize_tables()
        print("sessions、messages 会话表已就绪。")
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
