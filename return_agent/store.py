import os
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

SEED_CREATED_AT = "2026-10-01T00:00:00Z"

# (order_id, order_line_id, owner_id, product_name, status, days_since_delivery,
#  purchased_qty, reserved_qty, returnable)
SEED_ORDER_LINES = [
    (1001, 101, "U001", "蓝色 T 恤", 1, 3, 2, 0, 1),
    (1001, 102, "U001", "黑色卫衣", 1, 0, 1, 0, 1),
    (1002, 201, "U001", "运动鞋", 0, 5, 1, 0, 1),
    (1002, 202, "U001", "帆布包", 1, 15, 1, 0, 1),
    (1003, 301, "U001", "限量手办", 1, 2, 1, 0, 0),
    (1003, 302, "U001", "白色衬衫", 1, 7, 2, 1, 1),
    (1004, 401, "U001", "牛仔裤", 1, 14, 2, 2, 1),
    (1005, 501, "U002", "蓝色 T 恤", 1, 3, 2, 0, 1),
]

# (request_id, owner_id, order_line_id, quantity, policy_version, status)
SEED_RETURN_REQUESTS = [
    (9001, "U001", 302, 1, "policy-v1", "submitted"),
    (9002, "U001", 401, 2, "policy-v1", "submitted"),
]

ORDER_LINE_COLUMNS = (
    "order_id, order_line_id, product_name, status, days_since_delivery, "
    "returnable, purchased_qty, reserved_qty"
)


class StoreError(Exception):
    pass


class StoreTimeout(StoreError):
    pass


def _to_store_error(e, context):
    code = getattr(e, "sqlite_errorcode", None)
    if code is not None:
        if code == getattr(sqlite3, "SQLITE_BUSY", 5):
            return StoreTimeout(f"{context}: {e}")
        return StoreError(f"{context}: {e}")
    if "database is locked" in str(e).lower():
        return StoreTimeout(f"{context}: {e}")
    return StoreError(f"{context}: {e}")


def connect(path=":memory:"):
    try:
        if path != ":memory:":
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    except (sqlite3.Error, OSError) as e:
        raise _to_store_error(e, "connect") from e
    return conn


def init_schema(conn):
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (sqlite3.Error, OSError) as e:
        raise _to_store_error(e, "init_schema") from e


def seed_demo_data(conn):
    try:
        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO order_lines (order_id, order_line_id, owner_id, "
                "product_name, status, days_since_delivery, purchased_qty, reserved_qty, "
                "returnable) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                SEED_ORDER_LINES,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO return_requests (request_id, owner_id, order_line_id, "
                "quantity, policy_version, status, confirmation_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
                [row + (SEED_CREATED_AT,) for row in SEED_RETURN_REQUESTS],
            )
    except sqlite3.Error as e:
        raise _to_store_error(e, "seed_demo_data") from e


def _row_to_dict(row):
    return {
        "order_id": row["order_id"],
        "order_line_id": row["order_line_id"],
        "product_name": row["product_name"],
        "status": bool(row["status"]),
        "days_since_delivery": row["days_since_delivery"],
        "returnable": bool(row["returnable"]),
        "purchased_qty": row["purchased_qty"],
        "reserved_qty": row["reserved_qty"],
    }


def list_order_lines(conn, owner_id):
    try:
        rows = conn.execute(
            f"SELECT {ORDER_LINE_COLUMNS} FROM order_lines WHERE owner_id = ? "
            "ORDER BY order_id, order_line_id",
            (owner_id,),
        ).fetchall()
    except sqlite3.Error as e:
        raise _to_store_error(e, "list_order_lines") from e
    return [_row_to_dict(row) for row in rows]


def get_order_line(conn, order_line_id, owner_id):
    try:
        row = conn.execute(
            f"SELECT {ORDER_LINE_COLUMNS} FROM order_lines "
            "WHERE order_line_id = ? AND owner_id = ?",
            (order_line_id, owner_id),
        ).fetchone()
    except sqlite3.Error as e:
        raise _to_store_error(e, "get_order_line") from e
    return _row_to_dict(row) if row is not None else None
