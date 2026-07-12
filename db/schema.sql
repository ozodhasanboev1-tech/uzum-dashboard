-- ============================================================
-- Uzum Plus shaxsiy analitika dashboard - Postgres/Supabase sxema
-- ============================================================

-- Do'konlar ro'yxati (4 ta Uzum do'kon shu yerda saqlanadi)
CREATE TABLE IF NOT EXISTS shops (
    id            SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    uzum_shop_id  BIGINT NOT NULL UNIQUE,   -- Uzum tomonidagi shop ID (/v1/shops dan)
    api_token     TEXT NOT NULL,             -- Authorization header uchun token (Bearer PREFIKSSIZ)
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mahsulotlar (SKU) katalogi
CREATE TABLE IF NOT EXISTS products (
    id             SERIAL PRIMARY KEY,
    shop_id        INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    uzum_sku_id    BIGINT,
    sku_code       TEXT,                     -- masalan DOCTORF-DF1200GUL-ЛАВАНД
    title          TEXT,
    category       TEXT,
    barcode        TEXT,
    image_url      TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shop_id, sku_code)
);

-- Tannarx (sebestoimost) - qo'lda tahrirlanadigan jadval
CREATE TABLE IF NOT EXISTS product_costs (
    product_id     INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    cost_price     NUMERIC(14,2) NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by     TEXT
);

-- Buyurtmalar (/v1/finance/orders sync natijasi)
CREATE TABLE IF NOT EXISTS orders (
    id                 SERIAL PRIMARY KEY,
    shop_id            INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    uzum_order_id      BIGINT NOT NULL,
    order_date         TIMESTAMPTZ,
    status             TEXT,                 -- TO_WITHDRAW / PROCESSING / CANCELED / PARTIALLY_CANCELLED
    fulfillment_type   TEXT,                  -- FBO / FBS / DBS
    raw                JSONB,
    synced_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shop_id, uzum_order_id)
);

-- Buyurtma tarkibidagi mahsulotlar
CREATE TABLE IF NOT EXISTS order_items (
    id               SERIAL PRIMARY KEY,
    order_id         INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id       INTEGER REFERENCES products(id),
    sku_code         TEXT,
    qty              INTEGER NOT NULL DEFAULT 0,
    sale_price       NUMERIC(14,2) DEFAULT 0,   -- Цена продажи
    seller_profit    NUMERIC(14,2) DEFAULT 0,   -- Прибыль продавца (Uzum API dan)
    commission       NUMERIC(14,2) DEFAULT 0,
    logistics_cost   NUMERIC(14,2) DEFAULT 0,
    returned_qty     INTEGER DEFAULT 0
);

-- Xarajat/daromad jurnali (/v1/finance/expenses)
CREATE TABLE IF NOT EXISTS expenses (
    id                SERIAL PRIMARY KEY,
    shop_id           INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    uzum_payment_id   BIGINT NOT NULL,
    expense_date      TIMESTAMPTZ,
    category          TEXT,        -- Комиссия / Логистика / Маркетинг / Склад / Штраф ФБС / ...
    type              TEXT,        -- OUTCOME / INCOME
    source            TEXT,
    description       TEXT,
    amount            NUMERIC(14,2) DEFAULT 0,
    raw               JSONB,
    synced_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shop_id, uzum_payment_id)
);

-- Ombordagi qoldiqlar (FBO / FBS) - har sync'da snapshot sifatida yoziladi
CREATE TABLE IF NOT EXISTS stocks (
    id                SERIAL PRIMARY KEY,
    shop_id           INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    product_id        INTEGER REFERENCES products(id),
    fulfillment_type  TEXT,        -- FBO / FBS
    qty               INTEGER DEFAULT 0,
    cost_total        NUMERIC(14,2) DEFAULT 0,
    snapshot_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Nakladnoylar (FBO va FBS) - qabul/qaytarilgan/brak
CREATE TABLE IF NOT EXISTS invoices (
    id                SERIAL PRIMARY KEY,
    shop_id           INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    uzum_invoice_id   BIGINT NOT NULL,
    invoice_type      TEXT,        -- FBO / FBS / RETURN / DEFECT
    status            TEXT,
    sku_count         INTEGER DEFAULT 0,
    cost_total        NUMERIC(14,2) DEFAULT 0,
    created_at        TIMESTAMPTZ,
    raw                JSONB,
    UNIQUE (shop_id, uzum_invoice_id, invoice_type)
);

-- Qaytarilgan tovarlar
CREATE TABLE IF NOT EXISTS returns (
    id              SERIAL PRIMARY KEY,
    shop_id         INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
    uzum_return_id  BIGINT NOT NULL,
    product_id      INTEGER REFERENCES products(id),
    qty             INTEGER DEFAULT 0,
    amount          NUMERIC(14,2) DEFAULT 0,
    reason          TEXT,
    return_date     TIMESTAMPTZ,
    raw             JSONB,
    UNIQUE (shop_id, uzum_return_id)
);

-- Sync jarayoni logi (nosozliklarni kuzatish uchun)
CREATE TABLE IF NOT EXISTS sync_log (
    id          SERIAL PRIMARY KEY,
    shop_id     INTEGER REFERENCES shops(id),
    entity      TEXT,             -- orders / expenses / products / stocks / invoices / returns
    status      TEXT,             -- OK / ERROR
    message     TEXT,
    synced_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Telegram bot orqali dashboardga kirishga ruxsat berilgan foydalanuvchilar
CREATE TABLE IF NOT EXISTS telegram_users (
    chat_id    BIGINT PRIMARY KEY,
    name       TEXT,
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tezkor so'rovlar uchun indekslar
CREATE INDEX IF NOT EXISTS idx_orders_shop_date ON orders(shop_id, order_date);
CREATE INDEX IF NOT EXISTS idx_expenses_shop_date ON expenses(shop_id, expense_date);
CREATE INDEX IF NOT EXISTS idx_stocks_shop_snapshot ON stocks(shop_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_products_shop ON products(shop_id);
