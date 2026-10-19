import unittest

from return_agent import policy, store
from return_agent.tools import get_return_policy, query_orders

ENVELOPE_KEYS = {"ok", "data", "error"}
ERROR_KEYS = {"category", "code", "message"}


def seeded_conn():
    conn = store.connect(":memory:")
    store.init_schema(conn)
    store.seed_demo_data(conn)
    return conn


class QueryOrdersTest(unittest.TestCase):
    def setUp(self):
        self.conn = seeded_conn()

    def tearDown(self):
        self.conn.close()

    def test_returns_current_user_lines_without_owner_id(self):
        result = query_orders(self.conn, "U001")
        self.assertIs(result["ok"], True)
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["data"]), 7)
        for line in result["data"]:
            self.assertNotIn("owner_id", line)

    def test_invalid_identity_is_input_error(self):
        for identity in (None, "", "   ", 123):
            with self.subTest(identity=identity):
                result = query_orders(self.conn, identity)
                self.assertIs(result["ok"], False)
                self.assertIsNone(result["data"])
                self.assertEqual(result["error"]["category"], "input")
                self.assertEqual(result["error"]["code"], "INVALID_IDENTITY")

    def test_store_failure_is_system_error(self):
        conn = seeded_conn()
        conn.close()
        result = query_orders(conn, "U001")
        self.assertIs(result["ok"], False)
        self.assertIsNone(result["data"])
        self.assertEqual(result["error"]["category"], "system")
        self.assertEqual(result["error"]["code"], "STORE_UNAVAILABLE")

    def test_valid_identity_without_orders_returns_empty_list(self):
        result = query_orders(self.conn, "U999")
        self.assertIs(result["ok"], True)
        self.assertEqual(result["data"], [])
        self.assertIsNone(result["error"])


class GetReturnPolicyTest(unittest.TestCase):
    def test_returns_policy_from_single_source(self):
        result = get_return_policy()
        self.assertIs(result["ok"], True)
        self.assertIsNone(result["error"])
        self.assertEqual(result["data"]["version"], policy.POLICY_VERSION)
        self.assertEqual(result["data"]["window_days"], policy.WINDOW_DAYS)
        self.assertTrue(result["data"]["summary"])


class EnvelopeShapeTest(unittest.TestCase):
    def test_success_envelope_keys(self):
        conn = seeded_conn()
        try:
            results = [query_orders(conn, "U001"), get_return_policy()]
        finally:
            conn.close()
        for result in results:
            with self.subTest(result=result["ok"]):
                self.assertEqual(set(result), ENVELOPE_KEYS)

    def test_failure_envelope_keys(self):
        conn = seeded_conn()
        invalid_identity = query_orders(conn, None)
        conn.close()
        store_failure = query_orders(conn, "U001")
        for result in (invalid_identity, store_failure):
            with self.subTest(code=result["error"]["code"]):
                self.assertEqual(set(result), ENVELOPE_KEYS)
                self.assertEqual(set(result["error"]), ERROR_KEYS)


if __name__ == "__main__":
    unittest.main()
