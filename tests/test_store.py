import os
import sqlite3
import tempfile
import unittest

from return_agent import store
from return_agent.store import (
    connect,
    get_order_line,
    init_schema,
    list_order_lines,
    seed_demo_data,
)
from return_agent.validation import OK, REASON_CODES
from return_agent.tools import REJECTION_MESSAGES


class RejectionMessageCoverageTest(unittest.TestCase):
    def test_every_reason_code_has_a_message(self):
        missing = set(REASON_CODES) - {OK} - set(REJECTION_MESSAGES)
        self.assertEqual(missing, set(), f"缺少文案的原因码: {missing}")


def seeded_conn():
    conn = connect(":memory:")
    init_schema(conn)
    seed_demo_data(conn)
    return conn


def count_rows(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = seeded_conn()

    def tearDown(self):
        self.conn.close()

    def test_list_order_lines_returns_only_owner_rows_sorted(self):
        lines = list_order_lines(self.conn, "U001")
        self.assertEqual(len(lines), 7)
        keys = [(line["order_id"], line["order_line_id"]) for line in lines]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(
            [line["order_line_id"] for line in lines],
            [101, 102, 201, 202, 301, 302, 401],
        )
        self.assertNotIn(501, [line["order_line_id"] for line in lines])
        for line in lines:
            self.assertNotIn("owner_id", line)

    def test_get_order_line_converts_booleans(self):
        line = get_order_line(self.conn, 101, "U001")
        self.assertIs(line["status"], True)
        self.assertIs(line["returnable"], True)
        self.assertEqual(
            set(line),
            {
                "order_id",
                "order_line_id",
                "product_name",
                "status",
                "days_since_delivery",
                "returnable",
                "purchased_qty",
                "reserved_qty",
            },
        )

    def test_get_order_line_filters_by_owner(self):
        self.assertIsNone(get_order_line(self.conn, 501, "U001"))
        self.assertIsNone(get_order_line(self.conn, 101, "U002"))

    def test_reserved_qty_matches_return_requests(self):
        for order_line_id in (302, 401):
            with self.subTest(order_line_id):
                line = get_order_line(self.conn, order_line_id, "U001")
                total = self.conn.execute(
                    "SELECT COALESCE(SUM(quantity), 0) FROM return_requests "
                    "WHERE order_line_id = ?",
                    (order_line_id,),
                ).fetchone()[0]
                self.assertEqual(line["reserved_qty"], total)

    def test_seed_demo_data_is_idempotent(self):
        before = (count_rows(self.conn, "order_lines"), count_rows(self.conn, "return_requests"))
        seed_demo_data(self.conn)
        seed_demo_data(self.conn)
        after = (count_rows(self.conn, "order_lines"), count_rows(self.conn, "return_requests"))
        self.assertEqual(before, after)
        self.assertEqual(after, (8, 2))


class StoreFailureTest(unittest.TestCase):
    def test_closed_connection_raises_store_error(self):
        conn = store.connect(":memory:")
        store.init_schema(conn)
        conn.close()
        with self.assertRaises(store.StoreError):
            store.list_order_lines(conn, "U001")


class StoreFilePersistenceTest(unittest.TestCase):
    def test_file_db_persists_across_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.db")
            conn = store.connect(path)
            store.init_schema(conn)
            store.seed_demo_data(conn)
            conn.close()

            conn2 = store.connect(path)
            rows = store.list_order_lines(conn2, "U001")
            self.assertEqual(len(rows), 7)
            self.assertEqual(
                store.get_order_line(conn2, 101, "U001")["order_line_id"], 101
            )
            conn2.close()


class RealLockTimeoutTest(unittest.TestCase):
    def test_real_lock_maps_to_store_timeout(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.db")
            holder = store.connect(path)
            store.init_schema(holder)
            store.seed_demo_data(holder)
            holder.execute("BEGIN IMMEDIATE")
            contender = sqlite3.connect(path, timeout=0)
            try:
                with self.assertRaises(store.StoreTimeout):
                    store.seed_demo_data(contender)
            finally:
                contender.close()
                holder.rollback()
                holder.close()


CONFIRMATION = {
    "confirmation_id": "c-001",
    "user_id": "U001",
    "order_line_id": 101,
    "quantity": 1,
    "policy_version": "policy-v1",
    "plan_hash": "a" * 64,
    "created_at": "2026-10-19T08:00:00Z",
    "expires_at": "2026-10-19T08:10:00Z",
}


CONFIRMATION_KEYS = {
    "confirmation_id", "user_id", "plan", "plan_hash", "policy_version",
    "created_at", "expires_at", "status", "request_id",
}
PLAN_KEYS = {"order_line_id", "quantity", "policy_version", "plan_hash"}


class StoreWriteTest(unittest.TestCase):
    def setUp(self):
        self.conn = seeded_conn()
        with store.transaction(self.conn):
            store.create_confirmation(self.conn, **CONFIRMATION)

    def tearDown(self):
        self.conn.close()

    def reserved(self, order_line_id):
        return get_order_line(self.conn, order_line_id, "U001")["reserved_qty"]

    def submit_in_transaction(self, confirmation_id="c-001", quantity=1):
        request_id = store.create_return_request(
            self.conn,
            owner_id="U001",
            order_line_id=101,
            quantity=quantity,
            policy_version="policy-v1",
            confirmation_id=confirmation_id,
            created_at="2026-10-19T08:01:00Z",
        )
        store.increment_reserved(self.conn, 101, quantity)
        return request_id

    def test_transaction_commits_request_and_reserved(self):
        with store.transaction(self.conn):
            request_id = self.submit_in_transaction()
        request = store.get_return_request_by_confirmation(self.conn, "c-001")
        self.assertEqual(request["request_id"], request_id)
        self.assertEqual(request["owner_id"], "U001")
        self.assertEqual(request["order_line_id"], 101)
        self.assertEqual(request["quantity"], 1)
        self.assertEqual(request["status"], "submitted")
        self.assertEqual(self.reserved(101), 1)

    def test_transaction_rolls_back_on_exception(self):
        with self.assertRaises(RuntimeError):
            with store.transaction(self.conn):
                self.submit_in_transaction()
                raise RuntimeError("boom")
        self.assertIsNone(store.get_return_request_by_confirmation(self.conn, "c-001"))
        self.assertEqual(self.reserved(101), 0)

    def test_transaction_rolls_back_when_increment_fails(self):
        with self.assertRaises(store.StoreError):
            with store.transaction(self.conn):
                self.submit_in_transaction(quantity=3)
        self.assertIsNone(store.get_return_request_by_confirmation(self.conn, "c-001"))
        self.assertEqual(self.reserved(101), 0)
        self.assertEqual(count_rows(self.conn, "return_requests"), 2)

    def test_confirmation_round_trip(self):
        stored = store.get_confirmation(self.conn, "c-001")
        self.assertEqual(stored, {
            "confirmation_id": "c-001",
            "user_id": "U001",
            "plan": {
                "order_line_id": 101,
                "quantity": 1,
                "policy_version": "policy-v1",
                "plan_hash": "a" * 64,
            },
            "plan_hash": "a" * 64,
            "policy_version": "policy-v1",
            "created_at": "2026-10-19T08:00:00Z",
            "expires_at": "2026-10-19T08:10:00Z",
            "status": "pending",
            "request_id": None,
        })

    def test_confirmation_shape_matches_contract(self):
        stored = store.get_confirmation(self.conn, "c-001")
        self.assertEqual(set(stored), CONFIRMATION_KEYS)
        self.assertEqual(set(stored["plan"]), PLAN_KEYS)
        self.assertEqual(stored["plan"]["plan_hash"], stored["plan_hash"])
        self.assertEqual(stored["plan"]["policy_version"], stored["policy_version"])

    def test_get_missing_confirmation_returns_none(self):
        self.assertIsNone(store.get_confirmation(self.conn, "missing"))

    def test_update_confirmation_status(self):
        with store.transaction(self.conn):
            request_id = self.submit_in_transaction()
            store.update_confirmation_status(self.conn, "c-001", "used", request_id)
        stored = store.get_confirmation(self.conn, "c-001")
        self.assertEqual(stored["status"], "used")
        self.assertEqual(stored["request_id"], request_id)

    def test_update_missing_confirmation_raises(self):
        with self.assertRaises(store.StoreError):
            with store.transaction(self.conn):
                store.update_confirmation_status(self.conn, "missing", "used")

    def test_duplicate_confirmation_id_raises(self):
        with store.transaction(self.conn):
            self.submit_in_transaction()
        with self.assertRaises(store.StoreError):
            with store.transaction(self.conn):
                self.submit_in_transaction()
        self.assertEqual(self.reserved(101), 1)

    def test_increment_reserved_beyond_purchased_raises(self):
        with self.assertRaises(store.StoreError):
            with store.transaction(self.conn):
                store.increment_reserved(self.conn, 101, 3)
        self.assertEqual(self.reserved(101), 0)

    def test_increment_missing_order_line_raises(self):
        with self.assertRaises(store.StoreError):
            with store.transaction(self.conn):
                store.increment_reserved(self.conn, 999, 1)

    def test_transaction_rejects_connection_already_in_transaction(self):
        store.increment_reserved(self.conn, 101, 1)  # 隐式事务，未提交
        self.assertTrue(self.conn.in_transaction)
        with self.assertRaises(store.StoreError):
            with store.transaction(self.conn):
                pass
        self.conn.rollback()
        self.assertEqual(self.reserved(101), 0)

    def test_return_request_requires_existing_confirmation(self):
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(store.StoreError):
            with store.transaction(self.conn):
                self.submit_in_transaction(confirmation_id="missing")
        self.assertIsNone(store.get_return_request_by_confirmation(self.conn, "missing"))
        self.assertEqual(self.reserved(101), 0)


class SchemaVersionTest(unittest.TestCase):
    def setUp(self):
        self.conn = store.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def user_version(self):
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def test_init_schema_sets_user_version(self):
        store.init_schema(self.conn)
        self.assertEqual(self.user_version(), store.SCHEMA_VERSION)

    def test_init_schema_is_repeatable_on_current_version(self):
        store.init_schema(self.conn)
        store.init_schema(self.conn)
        self.assertEqual(self.user_version(), store.SCHEMA_VERSION)

    def test_mismatched_user_version_raises(self):
        store.init_schema(self.conn)
        self.conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(store.StoreError):
            store.init_schema(self.conn)
        self.assertEqual(self.user_version(), 99)

    def test_new_db_gets_schema_version(self):
        conn = sqlite3.connect(":memory:")
        store.init_schema(conn)
        self.assertEqual(
            conn.execute("PRAGMA user_version").fetchone()[0],
            store.SCHEMA_VERSION,
        )
        conn.close()

    def test_legacy_db_without_version_is_rejected(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE order_lines (order_line_id INTEGER PRIMARY KEY)"
        )
        with self.assertRaises(store.StoreError):
            store.init_schema(conn)
        conn.close()

    def test_version_mismatch_is_rejected(self):
        conn = store.connect(":memory:")
        store.init_schema(conn)
        conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(store.StoreError):
            store.init_schema(conn)
        conn.close()


class TransactionLockTest(unittest.TestCase):
    def test_contended_write_lock_raises_store_timeout(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.db")
            conn1 = store.connect(path)
            store.init_schema(conn1)
            store.seed_demo_data(conn1)
            conn1.execute("BEGIN IMMEDIATE")
            conn2 = sqlite3.connect(path, timeout=0)
            try:
                with self.assertRaises(store.StoreTimeout):
                    with store.transaction(conn2):
                        pass
            finally:
                conn2.close()
                conn1.rollback()
                conn1.close()


if __name__ == "__main__":
    unittest.main()
