import os
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from return_agent import policy, store
from return_agent.config import CONFIRMATION_TTL_MINUTES
from return_agent.tools import compute_plan_hash, submit_return_request

USER = "U001"


def seeded_conn(path=":memory:"):
    conn = store.connect(path)
    store.init_schema(conn)
    store.seed_demo_data(conn)
    return conn


def make_confirmation(
    conn,
    order_line_id=101,
    quantity=1,
    user_id=USER,
    owner_id=USER,
    policy_version=None,
    expires_at=None,
):
    """读订单行、计算哈希并写入确认。写操作放在事务里，避免留下未提交事务。"""
    line = store.get_order_line(conn, order_line_id, owner_id)
    now = datetime.now(timezone.utc)
    confirmation_id = "c-" + uuid.uuid4().hex
    with store.transaction(conn):
        store.create_confirmation(
            conn,
            confirmation_id=confirmation_id,
            user_id=user_id,
            order_line_id=order_line_id,
            quantity=quantity,
            policy_version=policy_version or policy.POLICY_VERSION,
            plan_hash=compute_plan_hash(line, quantity),
            created_at=now.isoformat(),
            expires_at=expires_at or (now + timedelta(minutes=CONFIRMATION_TTL_MINUTES)).isoformat(),
        )
    return confirmation_id


def request_count(conn, confirmation_id):
    return conn.execute(
        "SELECT COUNT(*) FROM return_requests WHERE confirmation_id = ?",
        (confirmation_id,),
    ).fetchone()[0]


class SubmitReturnRequestTest(unittest.TestCase):
    def setUp(self):
        self.conn = seeded_conn()

    def tearDown(self):
        self.conn.close()

    def assertBusiness(self, result, code):
        self.assertIs(result["ok"], False)
        self.assertIsNone(result["data"])
        self.assertEqual(result["error"]["category"], "business")
        self.assertEqual(result["error"]["code"], code)

    def test_missing_confirmation_id(self):
        result = submit_return_request(self.conn, USER, None)
        self.assertBusiness(result, "NO_PENDING_CONFIRMATION")

    def test_unknown_confirmation_id(self):
        result = submit_return_request(self.conn, USER, "missing")
        self.assertBusiness(result, "NO_PENDING_CONFIRMATION")

    def test_confirmation_user_mismatch(self):
        confirmation_id = make_confirmation(self.conn, user_id="U002")
        result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertBusiness(result, "CONFIRMATION_MISMATCH")

    def test_invalid_confirmation(self):
        confirmation_id = make_confirmation(self.conn)
        with store.transaction(self.conn):
            store.update_confirmation_status(self.conn, confirmation_id, "invalid")
        result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertBusiness(result, "CONFIRMATION_INVALID")

    def test_expired_confirmation_is_marked_expired(self):
        confirmation_id = make_confirmation(
            self.conn, expires_at="2000-01-01T00:00:00+00:00"
        )
        result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertBusiness(result, "CONFIRMATION_EXPIRED")
        stored = store.get_confirmation(self.conn, confirmation_id)
        self.assertEqual(stored["status"], "expired")

    def test_plan_hash_mismatch_marks_invalid(self):
        confirmation_id = make_confirmation(self.conn)
        self.conn.execute(
            "UPDATE order_lines SET reserved_qty = 1 WHERE order_line_id = 101"
        )
        self.conn.commit()
        result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertBusiness(result, "PLAN_CHANGED")
        self.assertEqual(store.get_confirmation(self.conn, confirmation_id)["status"], "invalid")
        self.assertEqual(request_count(self.conn, confirmation_id), 0)

    def test_policy_version_mismatch_marks_invalid(self):
        confirmation_id = make_confirmation(self.conn, policy_version="policy-v0")
        result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertBusiness(result, "POLICY_CHANGED")
        self.assertEqual(store.get_confirmation(self.conn, confirmation_id)["status"], "invalid")

    def test_status_change_alone_is_plan_changed(self):
        confirmation_id = make_confirmation(self.conn)
        self.conn.execute("UPDATE order_lines SET status = 0 WHERE order_line_id = 101")
        self.conn.commit()
        result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertBusiness(result, "PLAN_CHANGED")
        self.assertEqual(store.get_confirmation(self.conn, confirmation_id)["status"], "invalid")

    def test_revalidation_when_hash_is_forced_to_match(self):
        # 人为构造哈希一致的状态变化，用于覆盖防御性重新校验分支。
        confirmation_id = make_confirmation(self.conn)
        self.conn.execute("UPDATE order_lines SET status = 0 WHERE order_line_id = 101")
        self.conn.commit()
        line = store.get_order_line(self.conn, 101, USER)
        new_hash = compute_plan_hash(line, 1)
        self.conn.execute(
            "UPDATE confirmations SET plan_hash = ? WHERE confirmation_id = ?",
            (new_hash, confirmation_id),
        )
        self.conn.commit()
        result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertBusiness(result, "NOT_DELIVERED")
        self.assertEqual(store.get_confirmation(self.conn, confirmation_id)["status"], "invalid")

    def test_successful_submit_writes_request_and_reserved(self):
        confirmation_id = make_confirmation(self.conn, quantity=1)
        before = store.get_order_line(self.conn, 101, USER)["reserved_qty"]
        result = submit_return_request(self.conn, USER, confirmation_id)

        self.assertIs(result["ok"], True)
        self.assertIsNone(result["error"])
        self.assertEqual(result["data"]["status"], "created")
        self.assertEqual(result["data"]["order_line_id"], 101)
        self.assertEqual(result["data"]["quantity"], 1)
        self.assertEqual(request_count(self.conn, confirmation_id), 1)
        request = store.get_return_request_by_confirmation(self.conn, confirmation_id)
        self.assertEqual(request["request_id"], result["data"]["request_id"])
        self.assertEqual(request["confirmation_id"], confirmation_id)
        self.assertEqual(request["quantity"], 1)
        self.assertEqual(store.get_order_line(self.conn, 101, USER)["reserved_qty"], before + 1)
        stored = store.get_confirmation(self.conn, confirmation_id)
        self.assertEqual(stored["status"], "used")
        self.assertEqual(stored["request_id"], result["data"]["request_id"])

    def test_second_submit_is_idempotent(self):
        confirmation_id = make_confirmation(self.conn)
        first = submit_return_request(self.conn, USER, confirmation_id)
        reserved = store.get_order_line(self.conn, 101, USER)["reserved_qty"]
        second = submit_return_request(self.conn, USER, confirmation_id)

        self.assertIs(second["ok"], True)
        self.assertEqual(second["data"]["status"], "already_exists")
        self.assertEqual(second["data"]["request_id"], first["data"]["request_id"])
        self.assertEqual(request_count(self.conn, confirmation_id), 1)
        self.assertEqual(store.get_order_line(self.conn, 101, USER)["reserved_qty"], reserved)

    def test_increment_failure_rolls_back(self):
        confirmation_id = make_confirmation(self.conn)
        before = store.get_order_line(self.conn, 101, USER)["reserved_qty"]
        with patch(
            "return_agent.tools.store.increment_reserved",
            side_effect=store.StoreError("boom"),
        ):
            result = submit_return_request(self.conn, USER, confirmation_id)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["error"]["category"], "system")
        self.assertEqual(result["error"]["code"], "TRANSACTION_FAILED")
        self.assertEqual(request_count(self.conn, confirmation_id), 0)
        self.assertEqual(store.get_order_line(self.conn, 101, USER)["reserved_qty"], before)
        self.assertEqual(store.get_confirmation(self.conn, confirmation_id)["status"], "pending")


class ConcurrentSubmitTest(unittest.TestCase):
    def test_two_connections_create_one_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "demo.db")
            conn = seeded_conn(path)
            confirmation_id = make_confirmation(conn)
            conn.close()

            results = []

            def submit():
                own = store.connect(path)
                try:
                    results.append(submit_return_request(own, USER, confirmation_id))
                finally:
                    own.close()

            threads = [threading.Thread(target=submit) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))

            self.assertEqual(len(results), 2)
            for result in results:
                self.assertIs(result["ok"], True, result)
            self.assertEqual(
                sorted(result["data"]["status"] for result in results),
                ["already_exists", "created"],
            )
            request_ids = {result["data"]["request_id"] for result in results}
            self.assertEqual(len(request_ids), 1)

            check = store.connect(path)
            try:
                self.assertEqual(request_count(check, confirmation_id), 1)
                self.assertEqual(store.get_order_line(check, 101, USER)["reserved_qty"], 1)
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
