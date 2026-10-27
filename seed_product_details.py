"""第六步：只准备少量明确标记的纯文本详情，不更新已有详情。"""
import sys

import pymysql

from app.config import AppError
from app.storage import connect


def seed_details():
    examples = [
        ("DEMO-PEN-0000", "练习说明：得力黑色0.5mm签字笔，用于本项目商品查询演示。",
         "练习包装：按支销售；没有提供盒装数量，不能换算一盒有几支。", "练习使用说明：用于纸面书写，本数据不包含速干、防水等性能承诺。"),
        ("DEMO-PEN-1000", "练习说明：晨光黑色0.5mm签字笔，用于本项目商品查询演示。",
         "练习包装：按支销售；没有提供盒装数量，不能换算一盒有几支。", "练习使用说明：用于纸面书写，请以实物标签为准。"),
        ("DEMO-ERASER-0", "练习说明：得力白色小号橡皮，用于本项目商品查询演示。",
         "练习包装：按块销售；没有提供整包数量。", "练习使用说明：用于铅笔书写擦除示例，不提供性能保证。"),
    ]
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS product_details (
                        sku VARCHAR(40) PRIMARY KEY,
                        description TEXT NOT NULL,
                        package_notes TEXT NOT NULL,
                        usage_notes TEXT NOT NULL,
                        CONSTRAINT fk_product_details FOREIGN KEY (sku) REFERENCES products(sku)
                    ) ENGINE=InnoDB
                """)
                inserted = 0
                for row in examples:
                    cursor.execute("SELECT sku FROM products WHERE sku = %s", (row[0],))
                    if not cursor.fetchone():
                        raise AppError("缺少对应练习商品，请先运行seed_products.py。")
                    cursor.execute("SELECT sku FROM product_details WHERE sku = %s", (row[0],))
                    if cursor.fetchone() is None:
                        cursor.execute("INSERT INTO product_details (sku, description, package_notes, usage_notes) VALUES (%s, %s, %s, %s)", row)
                        inserted += 1
                connection.commit()
                return inserted
    except pymysql.MySQLError:
        raise AppError("详情初始化失败，请核对建表权限和已有表结构。") from None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(f"详情练习表就绪，新增{seed_details()}条说明；原商品未修改。")
    except AppError as exc:
        print(str(exc))
        sys.exit(1)
