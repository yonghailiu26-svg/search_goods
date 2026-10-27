import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env.dev")


class AppError(Exception):
    """只携带可公开的错误提示，不包含密钥或原始异常。"""

    def __init__(self, message: str, *, code: str = "app_error", diagnostics: dict | None = None):
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise AppError(f"请在本地配置 {name}。")
    return value


def integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except ValueError:
        raise AppError(f"{name} 必须是 {minimum} 到 {maximum} 之间的整数。") from None
