"""
Shaxsiy Uzum analitika dashboard - FastAPI backend.

Ishga tushirish (lokal test uchun):
    pip install -r requirements.txt
    export DATABASE_URL=postgresql://...   (Supabase connection string)
    export DASHBOARD_PASSWORD=your-secret
    uvicorn main:app --reload --port 8000

Railway/Render'ga joylashtirishda shu buyruq Procfile/Start command sifatida ishlatiladi:
    uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import os
import logging
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text
from pydantic import BaseModel

from db import get_conn, init_db
import sync as sync_module
import queries

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "changeme")
AUTH_TOKEN = os.environ.get("DASHBOARD_TOKEN", "static-dev-token-please-change")
SYNC_INTERVAL_MINUTES = int(os.environ.get("SYNC_INTERVAL_MINUTES", "30"))

app = FastAPI(title="Uzum Plus - shaxsiy dashboard API")


@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.exception("Unhandled error on %s", request.url)
    return JSONResponse(status_code=500, content={
        "error": str(exc),
        "traceback": traceback.format_exc(),
    })

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- Auth ----------------
class LoginBody(BaseModel):
    password: str


def require_auth(authorization: Optional[str] = Header(None)):
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {AUTH_TOKEN}"):
        raise HTTPException(401, "Ruxsat yo'q")
    return True


@app.post("/api/auth/login")
def login(body: LoginBody):
    if not hmac.compare_digest(body.password, DASHBOARD_PASSWORD):
        raise HTTPException(401, "Parol noto'g'ri")
    return {"token": AUTH_TOKEN}


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


# ---------------- Shops ----------------
@app.get("/api/shops", dependencies=[Depends(require_auth)])
def list_shops():
    with get_conn() as conn:
        rows = conn.execute(text("SELECT id, name, uzum_shop_id, is_active FROM shops ORDER BY id")).fetchall()
        return [dict(r._mapping) for r in rows]


class ShopBody(BaseModel):
    name: str
    uzum_shop_id: int
    api_token: str


@app.post("/api/shops", dependencies=[Depends(require_auth)])
def add_shop(body: ShopBody):
    with get_conn() as conn:
        conn.execute(text("""
            INSERT INTO shops (name, uzum_shop_id, api_token) VALUES (:n, :u, :t)
            ON CONFLICT (uzum_shop_id) DO UPDATE SET name = EXCLUDED.name, api_token = EXCLUDED.api_token
        """), {"n": body.name, "u": body.uzum_shop_id, "t": body.api_token})
    return {"ok": True}


# ---------------- Summary (Bosh sahifa) ----------------
def _ids(shop_ids: Optional[str]):
    return [int(x) for x in shop_ids.split(",")] if shop_ids else None


@app.get("/api/summary", dependencies=[Depends(require_auth)])
def summary(date_from: str, date_to: str, shop_ids: Optional[str] = None):
    return queries.get_summary(date_from, date_to, _ids(shop_ids))


# ---------------- Hourly (Soatlik savdo) ----------------
@app.get("/api/hourly", dependencies=[Depends(require_auth)])
def hourly(date: str, shop_ids: Optional[str] = None):
    return queries.get_hourly(date, _ids(shop_ids))


# ---------------- Sales & stock (Продажа и остатки) ----------------
@app.get("/api/sales-stock", dependencies=[Depends(require_auth)])
def sales_stock(date_from: str, date_to: str, shop_ids: Optional[str] = None):
    return queries.get_sales_stock(date_from, date_to, _ids(shop_ids))


# ---------------- Expenses ledger ----------------
@app.get("/api/expenses", dependencies=[Depends(require_auth)])
def list_expenses(date_from: str, date_to: str, shop_ids: Optional[str] = None,
                   category: Optional[str] = None, page: int = 0, size: int = 100):
    return queries.get_expenses(date_from, date_to, _ids(shop_ids), category, page, size)


# ---------------- Product costs (tannarx) ----------------
@app.get("/api/costs", dependencies=[Depends(require_auth)])
def list_costs(shop_ids: Optional[str] = None):
    return queries.get_costs(_ids(shop_ids))


class CostBody(BaseModel):
    cost_price: float
    updated_by: Optional[str] = "dashboard"


@app.put("/api/costs/{product_id}", dependencies=[Depends(require_auth)])
def update_cost(product_id: int, body: CostBody):
    with get_conn() as conn:
        conn.execute(text("""
            INSERT INTO product_costs (product_id, cost_price, updated_at, updated_by)
            VALUES (:pid, :cp, now(), :by)
            ON CONFLICT (product_id) DO UPDATE SET
                cost_price = EXCLUDED.cost_price, updated_at = now(), updated_by = EXCLUDED.updated_by
        """), {"pid": product_id, "cp": body.cost_price, "by": body.updated_by})
    return {"ok": True}


# ---------------- Manual sync trigger ----------------
# sync_all() bir necha daqiqa davom etadi (5 do'kon x bir nechta Uzum endpoint).
# Uni to'g'ridan-to'g'ri (synchronous) chaqirsak, FastAPI'ning yagona ishchi jarayoni
# butunlay band bo'lib qoladi - shu vaqt ichida login ham, boshqa hech narsa ham
# ishlamay qoladi. Shuning uchun fon oqimida (background thread) ishga tushiramiz.
import threading

_sync_state = {"running": False, "last_finished_at": None, "last_error": None}


def _run_sync_background():
    _sync_state["running"] = True
    _sync_state["last_error"] = None
    try:
        sync_module.sync_all()
    except Exception as e:
        logger.exception("Fon sync xatosi")
        _sync_state["last_error"] = str(e)
    finally:
        _sync_state["running"] = False
        _sync_state["last_finished_at"] = datetime.now(timezone.utc).isoformat()


@app.post("/api/sync/run", dependencies=[Depends(require_auth)])
def run_sync_now():
    if _sync_state["running"]:
        return {"ok": True, "already_running": True}
    t = threading.Thread(target=_run_sync_background, daemon=True)
    t.start()
    return {"ok": True, "started": True}


@app.get("/api/sync/status", dependencies=[Depends(require_auth)])
def sync_status():
    return _sync_state


# ---------------- Scheduler ----------------
scheduler = BackgroundScheduler()


@app.on_event("startup")
def on_startup():
    try:
        init_db()
    except Exception:
        logger.exception("init_db xatosi (jadvallar allaqachon mavjud bo'lishi mumkin)")
    scheduler.add_job(sync_module.sync_all, "interval", minutes=SYNC_INTERVAL_MINUTES, id="sync_all", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler ishga tushdi: har %d daqiqada sync", SYNC_INTERVAL_MINUTES)


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown()


# ---------------- Frontend (statik fayllar) ----------------
# Railway'da Root Directory "backend" ga o'rnatilgani uchun frontend fayllari
# ham backend/frontend/ ichida bo'lishi kerak (repo ildizidagi frontend/ ga
# Railway build konteksti yeta olmaydi).
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def root():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
