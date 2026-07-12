"""
Umumiy SQL so'rovlar - ham FastAPI (main.py), ham Telegram bot (bot.py) shulardan
foydalanadi, shunda ikkalasida bir xil hisob-kitob mantig'i ishlaydi.
"""

from sqlalchemy import text
from db import get_conn


def get_summary(date_from: str, date_to: str, shop_ids: list[int] | None = None) -> dict:
    params = {"df": date_from, "dt": date_to}
    shop_filter = ""
    if shop_ids:
        shop_filter = "AND o.shop_id = ANY(:ids)"
        params["ids"] = shop_ids

    with get_conn() as conn:
        revenue_row = conn.execute(text(f"""
            SELECT COALESCE(SUM(oi.sale_price * oi.qty), 0) AS revenue,
                   COALESCE(SUM(oi.seller_profit), 0) AS payout,
                   COUNT(DISTINCT o.id) AS total_orders,
                   COUNT(DISTINCT o.id) FILTER (WHERE o.status = 'CANCELED') AS cancelled
            FROM orders o
            JOIN order_items oi ON oi.order_id = o.id
            WHERE o.order_date BETWEEN :df AND :dt {shop_filter}
        """), params).fetchone()

        expenses_rows = conn.execute(text(f"""
            SELECT category, SUM(amount) AS total
            FROM expenses e
            WHERE e.expense_date BETWEEN :df AND :dt AND e.type = 'OUTCOME'
            {shop_filter.replace('o.shop_id', 'e.shop_id')}
            GROUP BY category ORDER BY total DESC
        """), params).fetchall()

        stock_row = conn.execute(text(f"""
            SELECT fulfillment_type, SUM(qty) AS qty, SUM(cost_total) AS cost
            FROM stocks s
            WHERE snapshot_at = (SELECT MAX(snapshot_at) FROM stocks)
            {shop_filter.replace('o.shop_id', 's.shop_id')}
            GROUP BY fulfillment_type
        """), params).fetchall()

        total_expenses = sum(r.total for r in expenses_rows) if expenses_rows else 0
        net_profit = float(revenue_row.payout or 0) - float(total_expenses)

        return {
            "revenue": float(revenue_row.revenue or 0),
            "payout": float(revenue_row.payout or 0),
            "net_profit": net_profit,
            "total_orders": revenue_row.total_orders,
            "cancelled_orders": revenue_row.cancelled,
            "expenses_by_category": [{"category": r.category, "amount": float(r.total)} for r in expenses_rows],
            "stock_by_type": [{"type": r.fulfillment_type, "qty": r.qty, "cost": float(r.cost or 0)} for r in stock_row],
        }


def get_hourly(date: str, shop_ids: list[int] | None = None) -> list[dict]:
    params = {"d": date}
    shop_filter = ""
    if shop_ids:
        shop_filter = "AND shop_id = ANY(:ids)"
        params["ids"] = shop_ids
    with get_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT EXTRACT(HOUR FROM order_date) AS hour, COUNT(*) AS cnt
            FROM orders WHERE order_date::date = :d {shop_filter}
            GROUP BY hour ORDER BY hour
        """), params).fetchall()
        return [{"hour": int(r.hour), "count": r.cnt} for r in rows]


def get_sales_stock(date_from: str, date_to: str, shop_ids: list[int] | None = None) -> list[dict]:
    params = {"df": date_from, "dt": date_to}
    shop_filter = ""
    if shop_ids:
        shop_filter = "AND o.shop_id = ANY(:ids)"
        params["ids"] = shop_ids
    with get_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT p.id AS product_id, p.title, p.sku_code,
                   COALESCE(SUM(oi.qty), 0) AS sold,
                   COALESCE(SUM(oi.sale_price * oi.qty), 0) AS revenue,
                   COALESCE(SUM(oi.seller_profit), 0) AS payout,
                   COALESCE(pc.cost_price, 0) AS cost_price
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            LEFT JOIN products p ON p.sku_code = oi.sku_code AND p.shop_id = o.shop_id
            LEFT JOIN product_costs pc ON pc.product_id = p.id
            WHERE o.order_date BETWEEN :df AND :dt {shop_filter}
            GROUP BY p.id, p.title, p.sku_code, pc.cost_price
            ORDER BY sold DESC
        """), params).fetchall()
        result = []
        for r in rows:
            net = float(r.payout) - float(r.cost_price) * r.sold
            result.append({
                "product_id": r.product_id, "title": r.title, "sku_code": r.sku_code,
                "sold": r.sold, "revenue": float(r.revenue), "payout": float(r.payout),
                "net_profit": net,
            })
        return result


def get_expenses(date_from: str, date_to: str, shop_ids: list[int] | None = None,
                  category: str | None = None, page: int = 0, size: int = 100) -> list[dict]:
    params = {"df": date_from, "dt": date_to, "lim": size, "off": page * size}
    filters = ""
    if shop_ids:
        filters += " AND shop_id = ANY(:ids)"
        params["ids"] = shop_ids
    if category:
        filters += " AND category = :cat"
        params["cat"] = category
    with get_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT id, shop_id, expense_date, category, type, description, amount
            FROM expenses WHERE expense_date BETWEEN :df AND :dt {filters}
            ORDER BY expense_date DESC LIMIT :lim OFFSET :off
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]


def get_costs(shop_ids: list[int] | None = None) -> list[dict]:
    params = {}
    filters = ""
    if shop_ids:
        filters = "WHERE p.shop_id = ANY(:ids)"
        params["ids"] = shop_ids
    with get_conn() as conn:
        rows = conn.execute(text(f"""
            SELECT p.id AS product_id, p.title, p.sku_code, p.shop_id,
                   COALESCE(pc.cost_price, 0) AS cost_price
            FROM products p
            LEFT JOIN product_costs pc ON pc.product_id = p.id
            {filters}
            ORDER BY p.title
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]
