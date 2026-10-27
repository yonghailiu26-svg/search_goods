"""第四步A真实MySQL验收，不调用DeepSeek；保留两个练习会话供Navicat查看。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pymysql

from app.config import AppError
from app.session_repository import create_session, load_session, save_round


def verify():
    first_id = create_session()
    second_id = create_session()
    initial = {"category": "签字笔", "color": "黑色", "spec": "0.5mm", "max_price_fen": 500, "limit": 5}
    save_round(first_id, initial, "练习：找黑色0.5mm签字笔，预算5元", "练习回复：已记录筛选条件，此处没有请求模型。")
    updated = {**initial, "brand": "得力"}
    save_round(first_id, updated, "练习：换得力，其他不变", "练习回复：品牌已改为得力，此处没有查询商品。")
    expected = load_session(first_id)
    assert expected["requirements"] == updated
    assert [row["role"] for row in expected["history"]] == ["user", "assistant", "user", "assistant"]
    isolated = load_session(second_id)
    assert isolated["requirements"] == {} and isolated["history"] == []

    # 新进程不能共享本进程的内存字典；读到相同数据证明来自MySQL。
    source = "import json,sys; from app.session_repository import load_session; print(json.dumps(load_session(sys.argv[1]),ensure_ascii=False))"
    child = subprocess.run(
        [sys.executable, "-c", source, first_id], cwd=Path(__file__).resolve().parent,
        capture_output=True, text=True, encoding="utf-8", check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert json.loads(child.stdout) == expected
    print("真实MySQL：需求JSON、消息顺序、会话隔离及跨Python进程读取均通过。")

    # 真实事务中先修改条件、插入一条消息，再模拟第二条写入失败。
    def fail_after_first_insert(cursor, query, rows):
        cursor.execute(query, rows[0])
        raise pymysql.OperationalError(1644, "verification-only failure")

    with patch.object(pymysql.cursors.DictCursor, "executemany", fail_after_first_insert):
        try:
            save_round(first_id, {**updated, "brand": "齐心"}, "回滚练习消息", "不应提交的回复")
        except AppError:
            pass
        else:
            raise AssertionError("模拟失败没有生效")
    assert load_session(first_id) == expected, "失败后留下了部分条件或消息"
    print("真实事务：写入中途失败后，条件与消息均已回滚，没有半轮数据。")
    print("练习会话ID：", first_id)
    print("独立空会话ID：", second_id)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        verify()
    except (AppError, AssertionError) as exc:
        print(str(exc))
        sys.exit(1)
    except subprocess.SubprocessError:
        print("跨进程读取验证失败，未输出子进程原始错误。")
        sys.exit(1)
