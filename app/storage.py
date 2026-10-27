"""数据库层：连接 MySQL、执行参数化 SQL，不调用模型。"""
import os

import pymysql

from app.config import AppError, integer, required
from app.schemas import SearchProductsArgs


def connect(*, with_database: bool = True):
    if required("MYSQL_DATABASE") != "agent_goods_practice":
        raise AppError("本课 MYSQL_DATABASE 必须为 agent_goods_practice。")
    try:
        return pymysql.connect(
            host=required("MYSQL_HOST"), port=integer("MYSQL_PORT", 3306, 1, 65535),
            user=required("MYSQL_USER"), password=os.getenv("MYSQL_PASSWORD", ""),
            database="agent_goods_practice" if with_database else None,
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5, read_timeout=10, write_timeout=10,
        )
    except pymysql.MySQLError:
        raise AppError("MySQL 连接失败，请检查本地配置、权限和练习库是否已初始化。") from None


def find_products(args: SearchProductsArgs) -> list[dict]:
    clauses = ["stock > 0"]
    values = []
    for column in ("category", "brand", "color", "spec"):
        value = getattr(args, column)
        if value is not None:
            clauses.append(f"{column} = %s")
            values.append(value)
    if args.keyword is not None:
        clauses.append("LOCATE(%s, name) > 0")
        values.append(args.keyword)
    if args.max_price_fen is not None:
        clauses.append("price_fen <= %s")
        values.append(args.max_price_fen)
    values.append(args.limit)
    sql = (
        "SELECT sku, name, category, brand, color, spec, unit, price_fen, stock "
        "FROM products WHERE " + " AND ".join(clauses)
        + " ORDER BY price_fen, sku LIMIT %s"
    )
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, values)
                return list(cursor.fetchall())
    except pymysql.MySQLError:
        raise AppError("商品查询失败，请检查练习表是否初始化；这不表示没有商品。") from None


def find_product_detail(sku: str) -> dict | None:
    sql = """
        SELECT p.sku, p.name, p.category, p.brand, p.color, p.spec,
               p.unit, p.price_fen, p.stock,
               d.description, d.package_notes, d.usage_notes
        FROM products AS p
        LEFT JOIN product_details AS d ON p.sku = d.sku
        WHERE p.sku = %s
    """
    try:
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (sku,))
                return cursor.fetchone()
    except pymysql.MySQLError:
        raise AppError("商品详情查询失败，请确认详情练习表已初始化。") from None
