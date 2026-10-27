"""显式运行才建库/建表并插入练习数据；API 启动不自动写入数据。"""
import sys

import pymysql

from app.config import AppError
from app.storage import connect


def seed() -> int:
    with connect(with_database=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE IF NOT EXISTS agent_goods_practice CHARACTER SET utf8mb4")
            cursor.execute("USE agent_goods_practice")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    sku VARCHAR(40) PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    category VARCHAR(40) NOT NULL,
                    brand VARCHAR(40) NOT NULL,
                    color VARCHAR(40) NOT NULL,
                    spec VARCHAR(40) NOT NULL,
                    unit VARCHAR(20) NOT NULL,
                    price_fen INT UNSIGNED NOT NULL,
                    stock INT UNSIGNED NOT NULL
                )
            """)
            rows = []
            for brand_index, brand in enumerate(("得力", "晨光", "齐心")):
                for color_index, color in enumerate(("黑色", "蓝色")):
                    for spec_index, spec in enumerate(("0.5mm", "0.7mm")):
                        for variant in range(2):
                            sku = f"DEMO-PEN-{brand_index}{color_index}{spec_index}{variant}"
                            rows.append((sku, f"练习数据·{brand}{color}{spec}签字笔{variant + 1}号",
                                         "签字笔", brand, color, spec, "支",
                                         150 + brand_index * 100 + variant * 400, 30))
            for index in range(4):
                rows.append((f"DEMO-ERASER-{index}", f"练习数据·得力白色橡皮{index + 1}号",
                             "橡皮", "得力", "白色", "小号", "块", 100 + index * 50, 20))
            # 已有 SKU 不更新、不删除。重复运行也不会生成重复商品。
            for row in rows:
                cursor.execute("SELECT sku FROM products WHERE sku = %s", (row[0],))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO products VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
            connection.commit()
            cursor.execute("SELECT COUNT(*) AS count FROM products")
            return cursor.fetchone()["count"]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(f"练习库初始化完成，products 共 {seed()} 条商品。")
    except (AppError, pymysql.MySQLError):
        print("初始化失败，请检查本地 MySQL 配置及建库/建表权限；未输出原始错误。")
        sys.exit(1)
