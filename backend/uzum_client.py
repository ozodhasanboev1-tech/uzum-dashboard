"""
Uzum Market Seller API klienti.

Rasmiy hujjat: https://api-seller.uzum.uz/api/seller-openapi/swagger/swagger-ui/webjars/swagger-ui/index.html
Auth: header "Authorization: <token>" (Bearer PREFIKSSIZ - swagger'da shunday yozilgan).

ESLATMA: bu klient rasmiy Swagger sxemasidagi parametr/javob shakllariga qarab yozilgan
(token bo'lmagani uchun real javoblar sinovdan o'tkazilmagan). Birinchi real
so'rovlardan keyin dict kalitlarini (masalan orderItems ichidagi maydonlar)
solishtirib, kerak bo'lsa sync.py dagi parser funksiyalarini moslashtiring.
"""

import time
import logging
from typing import Optional

import requests

logger = logging.getLogger("uzum_client")

BASE_URL = "https://api-seller.uzum.uz/api/seller-openapi"


class UzumApiError(Exception):
    pass


class UzumClient:
    def __init__(self, api_token: str, timeout: int = 30):
        self.api_token = api_token
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_token,
            "Accept": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{BASE_URL}{path}"
        for attempt in range(5):
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)

            # Rate-limit: 429 bo'lsa, header'dagi tavsiyaga qarab kutamiz
            if resp.status_code == 429:
                wait = float(resp.headers.get("x-ratelimit-replenish-rate", 2))
                logger.warning("Rate limit, %.1f soniya kutilmoqda...", wait)
                time.sleep(max(wait, 1))
                continue

            if resp.status_code >= 400:
                raise UzumApiError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")

            if not resp.content:
                return {}
            return resp.json()

        raise UzumApiError(f"{method} {path}: rate limit tufayli 5 urinishdan keyin ham muvaffaqiyatsiz")

    # ---------- Shop ----------
    def get_shops(self) -> list:
        """GET /v1/shops -> [{id, name}]"""
        return self._request("GET", "/v1/shops")

    # ---------- Finance ----------
    def get_finance_orders(self, date_from_ms: int, date_to_ms: int, shop_ids: list[int],
                            page: int = 0, size: int = 100, statuses: Optional[list[str]] = None,
                            group: bool = False) -> dict:
        """GET /v1/finance/orders -> {orderItems: [...], totalElements}"""
        params = {
            "page": page, "size": size, "group": str(group).lower(),
            "dateFrom": date_from_ms, "dateTo": date_to_ms,
        }
        # requests query-array format: shopIds=1&shopIds=2
        query = list(params.items()) + [("shopIds", sid) for sid in shop_ids]
        if statuses:
            query += [("statuses", s) for s in statuses]
        return self._request("GET", "/v1/finance/orders", params=query)

    def get_finance_expenses(self, date_from_ms: int, date_to_ms: int, shop_ids: list[int],
                              page: int = 0, size: int = 100) -> dict:
        """GET /v1/finance/expenses -> {payload: {payments: [...]}}"""
        query = [("page", page), ("size", size), ("dateFrom", date_from_ms), ("dateTo", date_to_ms)]
        query += [("shopIds", sid) for sid in shop_ids]
        return self._request("GET", "/v1/finance/expenses", params=query)

    # ---------- Products ----------
    def get_products(self, shop_id: int, page: int = 0, size: int = 100) -> dict:
        """GET /v1/product/shop/{shopId}"""
        params = {"page": page, "size": size}
        return self._request("GET", f"/v1/product/shop/{shop_id}", params=params)

    # ---------- Stocks (FBS) ----------
    def get_fbs_stocks(self, shop_id: int, page: int = 0, size: int = 100) -> dict:
        """GET /v3/fbs/sku/stocks (postranichno)"""
        params = {"shopId": shop_id, "page": page, "size": size}
        return self._request("GET", "/v3/fbs/sku/stocks", params=params)

    # ---------- FBS Orders ----------
    def get_fbs_orders(self, shop_ids: list[int], page: int = 0, size: int = 100,
                        date_from_ms: Optional[int] = None, date_to_ms: Optional[int] = None) -> dict:
        """GET /v2/fbs/orders"""
        query = [("page", page), ("size", size)]
        query += [("shopIds", sid) for sid in shop_ids]
        if date_from_ms:
            query.append(("dateFrom", date_from_ms))
        if date_to_ms:
            query.append(("dateTo", date_to_ms))
        return self._request("GET", "/v2/fbs/orders", params=query)

    # ---------- Invoices (FBO) ----------
    def get_invoices(self, shop_id: int, page: int = 0, size: int = 100) -> dict:
        """GET /v1/shop/{shopId}/invoice"""
        params = {"page": page, "size": size}
        return self._request("GET", f"/v1/shop/{shop_id}/invoice", params=params)

    # ---------- Returns ----------
    def get_returns(self, shop_id: int, page: int = 0, size: int = 100) -> dict:
        """GET /v1/shop/{shopId}/return"""
        params = {"page": page, "size": size}
        return self._request("GET", f"/v1/shop/{shop_id}/return", params=params)
