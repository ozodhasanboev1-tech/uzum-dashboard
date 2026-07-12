"""
Uzum API -> Postgres sync jarayoni.

4 ta do'kon uchun har X daqiqada (main.py dagi scheduler orqali) chaqiriladi:
  1. products   - SKU katalogini yangilaydi
  2. orders     - buyurtmalarni (finance/orders) tortib, orders + order_items ga yozadi
  3. expenses   - xarajat/daromad jurnalini tortadi
  4. stocks     - FBS qoldiqlarini snapshot sifatida yozadi

ESLATMA: Uzum javoblaridagi aniq maydon nomlari (masalan orderItems ichidagi
"skuTitle" yoki "sku") birinchi real so'rovdan keyin tekshirilishi va
kerak bo'lsa quyidagi .get(...) kalitlari moslashtirilishi kerak - hozircha
Swagger sxemasi asosida eng ehtimoliy nomlar ishlatilgan.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db import get_conn
from uzum_client import UzumClient, UzumApiError

logger = logging.getLogger("sync")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _log(conn, shop_id: int, entity: str, status: str, message: str = ""):
    conn.execute(
        text("INSERT INTO sync_log (shop_id, entity, status, message) VALUES (:s, :e, :st, :m)"),
        {"s": shop_id, "e": entity, "st": status, "m": message[:2000]},
    )


def get_active_shops(conn):
    rows = conn.execute(text("SELECT id, name, uzum_shop_id, api_token FROM shops WHERE is_active = true")).fetchall()
    return [dict(r._mapping) for r in rows]


def sync_products(conn, shop: dict):
    client = UzumClient(shop["api_token"])
    page = 0
    while True:
        data = client.get_products(shop["uzum_shop_id"], page=page, size=100)
        items = data.get("content") or data.get("skuList") or data if isinstance(data, list) else data.get("content", [])
        if not items:
            break
        for it in items:
            sku_code = it.get("skuTitle") or it.get("sku") or it.get("skuCode") or str(it.get("skuId", ""))
            conn.execute(text("""
                INSERT INTO products (shop_id, uzum_sku_id, sku_code, title, category, barcode, image_url, updated_at)
                VALUES (:shop_id, :sku_id, :sku_code, :title, :category, :barcode, :image_url, now())
                ON CONFLICT (shop_id, sku_code) DO UPDATE SET
                    title = EXCLUDED.title, category = EXCLUDED.category,
                    barcode = EXCLUDED.barcode, image_url = EXCLUDED.image_url, updated_at = now()
            """), {
                "shop_id": shop["id"], "sku_id": it.get("skuId") or it.get("id"),
                "sku_code": sku_code, "title": it.get("title") or it.get("productTitle"),
                "category": it.get("category"), "barcode": it.get("barcode"),
                "image_url": (it.get("photo") or {}).get("photoUrl") if isinstance(it.get("photo"), dict) else None,
            })
        if len(items) < 100:
            break
        page += 1
    _log(conn, shop["id"], "products", "OK")


def sync_orders(conn, shop: dict, days_back: int = 3):
    """So'nggi `days_back` kun ichidagi buyurtmalarni tortadi (qayta ishlash/bekor
    qilish holatlarini yangilab turish uchun oynani biroz orqaga surib olamiz)."""
    client = UzumClient(shop["api_token"])
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days_back)
    page = 0
    while True:
        data = client.get_finance_orders(_ms(date_from), _ms(date_to), [shop["uzum_shop_id"]], page=page, size=200)
        items = data.get("orderItems", [])
        if not items:
            break
        for it in items:
            order_id = it.get("orderId") or it.get("id")
            if not order_id:
                continue
            conn.execute(text("""
                INSERT INTO orders (shop_id, uzum_order_id, order_date, status, fulfillment_type, raw, synced_at)
                VALUES (:shop_id, :order_id, :order_date, :status, :ftype, :raw, now())
                ON CONFLICT (shop_id, uzum_order_id) DO UPDATE SET
                    status = EXCLUDED.status, raw = EXCLUDED.raw, synced_at = now()
                RETURNING id
            """), {
                "shop_id": shop["id"], "order_id": order_id,
                "order_date": it.get("dateCreated") or it.get("orderDate"),
                "status": it.get("status"), "ftype": it.get("deliveryType") or it.get("fulfillmentType"),
                "raw": _json(it),
            })
            row = conn.execute(text("SELECT id FROM orders WHERE shop_id=:s AND uzum_order_id=:o"),
                                {"s": shop["id"], "o": order_id}).fetchone()
            internal_order_id = row[0]
            # order_items ni to'liq qayta yozamiz (eng oson va xatoga chidamli usul)
            conn.execute(text("DELETE FROM order_items WHERE order_id=:oid"), {"oid": internal_order_id})
            for sku_item in it.get("orderItems", [it]):  # ba'zi javoblarda item darajasida keladi
                conn.execute(text("""
                    INSERT INTO order_items (order_id, sku_code, qty, sale_price, seller_profit, commission, logistics_cost, returned_qty)
                    VALUES (:oid, :sku, :qty, :price, :profit, :comm, :log, :ret)
                """), {
                    "oid": internal_order_id,
                    "sku": sku_item.get("skuTitle") or sku_item.get("sku"),
                    "qty": sku_item.get("amount") or sku_item.get("qty") or 1,
                    "price": sku_item.get("price") or sku_item.get("salePrice") or 0,
                    "profit": sku_item.get("sellerProfit") or sku_item.get("profit") or 0,
                    "comm": sku_item.get("commission") or 0,
                    "log": sku_item.get("logistics") or sku_item.get("logisticsCost") or 0,
                    "ret": sku_item.get("returnedAmount") or 0,
                })
        if len(items) < 200:
            break
        page += 1
    _log(conn, shop["id"], "orders", "OK")


def sync_expenses(conn, shop: dict, days_back: int = 3):
    client = UzumClient(shop["api_token"])
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days_back)
    page = 0
    while True:
        data = client.get_finance_expenses(_ms(date_from), _ms(date_to), [shop["uzum_shop_id"]], page=page, size=200)
        payments = (data.get("payload") or {}).get("payments", [])
        if not payments:
            break
        for p in payments:
            conn.execute(text("""
                INSERT INTO expenses (shop_id, uzum_payment_id, expense_date, category, type, source, description, amount, raw, synced_at)
                VALUES (:shop_id, :pid, :date, :cat, :type, :src, :descr, :amount, :raw, now())
                ON CONFLICT (shop_id, uzum_payment_id) DO UPDATE SET
                    amount = EXCLUDED.amount, raw = EXCLUDED.raw, synced_at = now()
            """), {
                "shop_id": shop["id"], "pid": p.get("id"),
                "date": p.get("dateService") or p.get("dateCreated"),
                "cat": p.get("name"), "type": p.get("type"), "src": p.get("source"),
                "descr": p.get("code"), "amount": p.get("amount") or p.get("paymentPrice") or 0,
                "raw": _json(p),
            })
        if len(payments) < 200:
            break
        page += 1
    _log(conn, shop["id"], "expenses", "OK")


def sync_stocks(conn, shop: dict):
    client = UzumClient(shop["api_token"])
    page = 0
    while True:
        data = client.get_fbs_stocks(shop["uzum_shop_id"], page=page, size=200)
        items = data.get("content") or data.get("stocks") or []
        if not items:
            break
        for it in items:
            sku_code = it.get("skuTitle") or it.get("sku")
            prod = conn.execute(text("SELECT id FROM products WHERE shop_id=:s AND sku_code=:sku"),
                                 {"s": shop["id"], "sku": sku_code}).fetchone()
            conn.execute(text("""
                INSERT INTO stocks (shop_id, product_id, fulfillment_type, qty, cost_total, snapshot_at)
                VALUES (:s, :p, 'FBS', :qty, :cost, now())
            """), {"s": shop["id"], "p": prod[0] if prod else None,
                    "qty": it.get("amount") or it.get("qty") or 0, "cost": it.get("costTotal") or 0})
        if len(items) < 200:
            break
        page += 1
    _log(conn, shop["id"], "stocks", "OK")


def _json(obj):
    import json
    return json.dumps(obj, default=str)


def sync_shop(shop: dict):
    with get_conn() as conn:
        for fn, name in [(sync_products, "products"), (sync_orders, "orders"),
                          (sync_expenses, "expenses"), (sync_stocks, "stocks")]:
            try:
                fn(conn, shop)
            except UzumApiError as e:
                logger.exception("Sync xatosi: %s / %s", shop["name"], name)
                _log(conn, shop["id"], name, "ERROR", str(e))


def sync_all():
    with get_conn() as conn:
        shops = get_active_shops(conn)
    for shop in shops:
        logger.info("Sync boshlandi: %s", shop["name"])
        sync_shop(shop)
    logger.info("Barcha do'konlar sync qilindi (%d ta)", len(shops))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sync_all()
