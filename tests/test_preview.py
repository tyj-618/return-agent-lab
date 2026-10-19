import re
import sqlite3
import unittest

from return_agent import policy, store
from return_agent.tools import preview_return_request

USER = "U001"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def seeded_conn():
    conn = store.connect(":memory:")
    store.init_schema(conn)
    store.seed_demo_data(conn)
    return conn


class _LockedConn:
    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")


class PreviewReturnRequestTest(unittest.TestCase):
    def setUp(self):
        self.conn = seeded_conn()

    def tearDown(self):
        self.conn.close()

    def assertError(self, result, category, code):
        self.assertIs(result["ok"], False)
        self.assertIsNone(result["data"])
        self.assertEqual(result["error"]["category"], category)
        self.assertEqual(result["error"]["code"], code)

    def test_allowed_returns_plan(self):
        result = preview_return_request(self.conn, USER, 101, 1)
        self.assertIs(result["ok"], True)
        self.assertIsNone(result["error"])
        self.assertIs(result["data"]["allowed"], True)
        plan = result["data"]["plan"]
        self.assertEqual(set(plan), {"order_line_id", "quantity", "policy_version", "plan_hash"})
        self.assertEqual(plan["order_line_id"], 101)
        self.assertEqual(plan["quantity"], 1)
        self.assertEqual(plan["policy_version"], policy.POLICY_VERSION)
        self.assertRegex(plan["plan_hash"], HEX64)

    def test_window_expired_is_business_rejection(self):
        result = preview_return_request(self.conn, USER, 202, 1)
        self.assertError(result, "business", "WINDOW_EXPIRED")

    def test_other_users_line_is_forbidden(self):
        result = preview_return_request(self.conn, USER, 501, 1)
        self.assertError(result, "business", "FORBIDDEN")

    def test_missing_line_is_forbidden_with_same_message(self):
        missing = preview_return_request(self.conn, USER, 999, 1)
        other = preview_return_request(self.conn, USER, 501, 1)
        self.assertError(missing, "business", "FORBIDDEN")
        self.assertEqual(missing, other)

    def test_invalid_identity(self):
        result = preview_return_request(self.conn, None, 101, 1)
        self.assertError(result, "input", "INVALID_IDENTITY")

    def test_string_order_line_id_is_invalid_argument(self):
        result = preview_return_request(self.conn, USER, "101", 1)
        self.assertError(result, "input", "INVALID_ARGUMENT")

    def test_closed_connection_is_store_unavailable(self):
        conn = seeded_conn()
        conn.close()
        result = preview_return_request(conn, USER, 101, 1)
        self.assertError(result, "system", "STORE_UNAVAILABLE")

    def test_locked_store_maps_to_timeout(self):
        result = preview_return_request(_LockedConn(), USER, 101, 1)
        self.assertError(result, "system", "TIMEOUT")

    def test_successful_preview_has_no_side_effects(self):
        def snapshot():
            reserved = self.conn.execute(
                "SELECT order_line_id, reserved_qty FROM order_lines ORDER BY order_line_id"
            ).fetchall()
            requests = self.conn.execute("SELECT COUNT(*) FROM return_requests").fetchone()[0]
            return [tuple(row) for row in reserved], requests

        before = snapshot()
        result = preview_return_request(self.conn, USER, 101, 1)
        self.assertIs(result["ok"], True)
        self.assertEqual(snapshot(), before)

    def test_plan_hash_is_deterministic_and_depends_on_quantity(self):
        first = preview_return_request(self.conn, USER, 101, 1)["data"]["plan"]["plan_hash"]
        second = preview_return_request(self.conn, USER, 101, 1)["data"]["plan"]["plan_hash"]
        two = preview_return_request(self.conn, USER, 101, 2)["data"]["plan"]["plan_hash"]
        self.assertEqual(first, second)
        self.assertNotEqual(first, two)

    def test_plan_hash_changes_when_reserved_qty_changes(self):
        first = preview_return_request(self.conn, USER, 101, 1)   # reserved=0
        self.conn.execute(
            "UPDATE order_lines SET reserved_qty = 1 WHERE order_line_id = 101"
        )
        self.conn.commit()
        second = preview_return_request(self.conn, USER, 101, 1)  # reserved=1，剩余仍够 1 件
        self.assertIs(first["ok"], True)
        self.assertIs(second["ok"], True)
        self.assertNotEqual(
            first["data"]["plan"]["plan_hash"],
            second["data"]["plan"]["plan_hash"],
        )

    def test_zero_quantity_is_business_invalid_quantity(self):
        result = preview_return_request(self.conn, USER, 101, 0)
        self.assertError(result, "business", "INVALID_QUANTITY")


if __name__ == "__main__":
    unittest.main()
