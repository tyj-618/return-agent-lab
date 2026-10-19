PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS order_lines (
    order_line_id       INTEGER PRIMARY KEY,
    order_id            INTEGER NOT NULL,
    owner_id            TEXT    NOT NULL,
    product_name        TEXT    NOT NULL,
    status              INTEGER NOT NULL CHECK (status IN (0, 1)),
    days_since_delivery INTEGER NOT NULL CHECK (days_since_delivery >= 0),
    purchased_qty       INTEGER NOT NULL CHECK (purchased_qty > 0),
    reserved_qty        INTEGER NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0),
    returnable          INTEGER NOT NULL CHECK (returnable IN (0, 1)),
    CHECK (reserved_qty <= purchased_qty)
);

CREATE INDEX IF NOT EXISTS idx_order_lines_owner ON order_lines(owner_id);

CREATE TABLE IF NOT EXISTS return_requests (
    request_id      INTEGER PRIMARY KEY,
    owner_id        TEXT    NOT NULL,
    order_line_id   INTEGER NOT NULL REFERENCES order_lines(order_line_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    policy_version  TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'submitted',
    confirmation_id TEXT    UNIQUE REFERENCES confirmations(confirmation_id),
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_order_line ON return_requests(order_line_id);

CREATE TABLE IF NOT EXISTS confirmations (
    confirmation_id TEXT PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    order_line_id   INTEGER NOT NULL REFERENCES order_lines(order_line_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    policy_version  TEXT    NOT NULL,
    plan_hash       TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    expires_at      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'used', 'invalid', 'expired')),
    request_id      INTEGER REFERENCES return_requests(request_id)
);

CREATE INDEX IF NOT EXISTS idx_confirmations_user ON confirmations(user_id, status);