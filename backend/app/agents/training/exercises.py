from dataclasses import dataclass


@dataclass(frozen=True)
class SQLCase:
    customers: tuple[tuple[int, str], ...]
    orders: tuple[tuple[int, int, int, str], ...]
    expected: tuple[tuple[int, int, int], ...]


TITLE = "Python 后端订单接口：SQL 聚合与 LEFT JOIN"
PROMPT = (
    "为 Python 后端的客户订单统计接口编写一条 SQLite SELECT 查询。"
    "返回每一位客户的 customer_id、paid_order_count、paid_total_cents，列顺序必须如此。"
    "仅统计 status='paid' 的订单，未付款订单不计入；没有已付款订单的客户也必须返回，"
    "计数和金额均为 0。保留全部客户，结果行的顺序不限。金额使用整数分。"
    "只能查询 customers、orders；不能修改数据或访问文件。"
)
TABLES = {
    "customers": ["id INTEGER PRIMARY KEY", "name TEXT NOT NULL"],
    "orders": [
        "id INTEGER PRIMARY KEY",
        "customer_id INTEGER",
        "amount_cents INTEGER",
        "status TEXT",
    ],
}
REFERENCE_SQL = """
SELECT c.id AS customer_id, COUNT(o.id) AS paid_order_count,
       COALESCE(SUM(o.amount_cents), 0) AS paid_total_cents
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id AND o.status = 'paid'
GROUP BY c.id
"""
CASES = (
    SQLCase(
        ((1, "模拟客户甲"), (2, "模拟客户乙"), (3, "模拟客户丙")),
        ((1, 1, 1200, "paid"), (2, 1, 800, "paid"), (3, 2, 500, "pending")),
        ((1, 2, 2000), (2, 0, 0), (3, 0, 0)),
    ),
    SQLCase(
        ((4, "模拟客户丁"), (5, "模拟客户戊")),
        ((10, 4, 0, "paid"), (11, 4, 100, "paid"), (12, 5, 900, "cancelled")),
        ((4, 2, 100), (5, 0, 0)),
    ),
    SQLCase(((9, "模拟客户己"),), (), ((9, 0, 0),)),
)
