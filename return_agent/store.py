import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1
_REQUIRED_TABLES = ("order_lines", "return_requests", "confirmations")

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
        conn.execute("PRAGMA foreign_keys = ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]

        if version == 0:
            placeholders = ",".join("?" for _ in _REQUIRED_TABLES)
            rows = conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' "
                f"AND name IN ({placeholders})",
                _REQUIRED_TABLES,
            ).fetchall()
            if rows:
                names = ", ".join(sorted(r[0] for r in rows))
                raise StoreError(
                    f"检测到旧版数据库（user_version=0，但已存在表：{names}）；"
                    "请删除旧库后重建（例如 rm -f return_agent/data/demo.db）"
                )
        elif version != SCHEMA_VERSION:
            raise StoreError(
                f"数据库 schema 版本不匹配（现有 {version}，期望 {SCHEMA_VERSION}）；"
                "请删除旧库后重建"
            )

        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    except sqlite3.Error as e:
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


CONFIRMATION_COLUMNS = (
    "confirmation_id", "user_id", "order_line_id", "quantity", "policy_version",
    "plan_hash", "created_at", "expires_at", "status", "request_id",
)

RETURN_REQUEST_COLUMNS = (
    "request_id", "owner_id", "order_line_id", "quantity", "policy_version",
    "status", "confirmation_id", "created_at",
)


@contextmanager
def transaction(conn):
    """BEGIN IMMEDIATE / COMMIT / ROLLBACK；失败时回滚并抛 StoreError。

    调用前连接不得处于事务中。块内抛出的非存储异常回滚后原样抛出，不包装成 StoreError。
    """
    if conn.in_transaction:
        raise StoreError("transaction: 连接已处于事务中，请先提交或回滚")
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as e:
        raise _to_store_error(e, "transaction.begin") from e
    try:
        yield conn
    except BaseException:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    try:
        conn.commit()
    except sqlite3.Error as e:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise _to_store_error(e, "transaction.commit") from e


def create_confirmation(conn, *, confirmation_id, user_id, order_line_id, quantity,
                        policy_version, plan_hash, created_at, expires_at):
    try:
        conn.execute(
            "INSERT INTO confirmations (confirmation_id, user_id, order_line_id, quantity, "
            "policy_version, plan_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (confirmation_id, user_id, order_line_id, quantity,
             policy_version, plan_hash, created_at, expires_at),
        )
    except sqlite3.Error as e:
        raise _to_store_error(e, "create_confirmation") from e


def get_confirmation(conn, confirmation_id):
    try:
        row = conn.execute(
            f"SELECT {', '.join(CONFIRMATION_COLUMNS)} FROM confirmations "
            "WHERE confirmation_id = ?",
            (confirmation_id,),
        ).fetchone()
    except sqlite3.Error as e:
        raise _to_store_error(e, "get_confirmation") from e
    if row is None:
        return None
    return {
        "confirmation_id": row["confirmation_id"],
        "user_id": row["user_id"],
        "plan": {
            "order_line_id": row["order_line_id"],
            "quantity": row["quantity"],
            "policy_version": row["policy_version"],
            "plan_hash": row["plan_hash"],
        },
        "plan_hash": row["plan_hash"],
        "policy_version": row["policy_version"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "status": row["status"],
        "request_id": row["request_id"],
    }


def update_confirmation_status(conn, confirmation_id, status, request_id=None):
    try:
        cursor = conn.execute(
            "UPDATE confirmations SET status = ?, request_id = COALESCE(?, request_id) "
            "WHERE confirmation_id = ?",
            (status, request_id, confirmation_id),
        )
    except sqlite3.Error as e:
        raise _to_store_error(e, "update_confirmation_status") from e
    if cursor.rowcount == 0:
        raise StoreError(f"update_confirmation_status: confirmation {confirmation_id} not found")


def create_return_request(conn, *, owner_id, order_line_id, quantity,
                          policy_version, confirmation_id, created_at):
    try:
        cursor = conn.execute(
            "INSERT INTO return_requests (owner_id, order_line_id, quantity, policy_version, "
            "confirmation_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, order_line_id, quantity, policy_version, confirmation_id, created_at),
        )
    except sqlite3.Error as e:
        raise _to_store_error(e, "create_return_request") from e
    return cursor.lastrowid


def get_return_request_by_confirmation(conn, confirmation_id):
    try:
        row = conn.execute(
            f"SELECT {', '.join(RETURN_REQUEST_COLUMNS)} FROM return_requests "
            "WHERE confirmation_id = ?",
            (confirmation_id,),
        ).fetchone()
    except sqlite3.Error as e:
        raise _to_store_error(e, "get_return_request_by_confirmation") from e
    return {col: row[col] for col in RETURN_REQUEST_COLUMNS} if row is not None else None


def increment_reserved(conn, order_line_id, quantity):
    try:
        cursor = conn.execute(
            "UPDATE order_lines SET reserved_qty = reserved_qty + ? WHERE order_line_id = ?",
            (quantity, order_line_id),
        )
    except sqlite3.Error as e:
        raise _to_store_error(e, "increment_reserved") from e
    if cursor.rowcount == 0:
        raise StoreError(f"increment_reserved: order line {order_line_id} not found")
