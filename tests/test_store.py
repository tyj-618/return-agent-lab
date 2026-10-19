import os
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


if __name__ == "__main__":
    unittest.main()
