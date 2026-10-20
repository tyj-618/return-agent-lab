import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from return_agent import store
from return_agent.agent import Agent
from return_agent.config import CONFIRMATION_TTL_MINUTES
from return_agent.trace import Tracer

USAGE = {"prompt_tokens": 10, "completion_tokens": 5}
USER = "U001"


def make_call(name, arguments, call_id="call_1"):
    return {
        "id": call_id,
        "name": name,
        "arguments": arguments,
        "arguments_raw": json.dumps(arguments),
    }


def calls_response(*calls):
    return {"text": None, "tool_calls": list(calls), "finish_reason": "tool_calls", "usage": USAGE}


def tool_response(name, arguments, call_id="call_1"):
    return calls_response(make_call(name, arguments, call_id))


def text_response(text):
    return {"text": text, "tool_calls": [], "finish_reason": "stop", "usage": USAGE}


class ScriptedLLM:
    """按顺序返回预设响应；脚本用完后重复最后一条。"""

    model = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.received = []

    def chat(self, messages, tools, timeout=None):
        self.received.append(copy.deepcopy(messages))
        index = min(len(self.received) - 1, len(self.responses) - 1)
        return copy.deepcopy(self.responses[index])


def preview_then_text(call_id, text):
    return [
        tool_response("preview_return_request", {"order_line_id": 101, "quantity": 1}, call_id),
        text_response(text),
    ]


class ConfirmFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(":memory:")
        store.init_schema(self.conn)
        store.seed_demo_data(self.conn)
        self.tracer = Tracer(os.path.join(self.tmp.name, "run.jsonl"))

    def tearDown(self):
        self.tracer.close()
        self.conn.close()
        self.tmp.cleanup()

    def agent(self, responses):
        return Agent(ScriptedLLM(responses), self.conn, USER, self.tracer)

    def tool_results(self, llm):
        results = []
        for messages in llm.received:
            for message in messages:
                if message["role"] == "tool":
                    results.append(json.loads(message["content"]))
        return results

    def test_preview_sets_pending_plan(self):
        agent = self.agent(preview_then_text("p1", "可以退 1 件。"))
        agent.run("退 1 件蓝色 T 恤")
        self.assertIsNotNone(agent.pending_plan)
        self.assertEqual(agent.pending_plan["order_line_id"], 101)
        self.assertEqual(agent.pending_plan["quantity"], 1)
        self.assertIsNone(agent.confirmation_id)

    def test_second_preview_invalidates_old_confirmation(self):
        agent = self.agent(
            preview_then_text("p1", "方案 1。") + preview_then_text("p2", "方案 2。")
        )
        agent.run("退 1 件")
        confirmation_id = agent.create_confirmation()
        self.assertIsNotNone(confirmation_id)
        agent.run("还是退 1 件")
        stored = store.get_confirmation(self.conn, confirmation_id)
        self.assertEqual(stored["status"], "invalid")
        self.assertIsNone(agent.confirmation_id)
        self.assertEqual(agent.pending_plan["order_line_id"], 101)

    def test_create_confirmation_without_plan_writes_nothing(self):
        agent = self.agent([])
        before = self.conn.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0]
        self.assertIsNone(agent.create_confirmation())
        after = self.conn.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0]
        self.assertEqual(before, after)

    def test_create_confirmation_persists_plan_fields(self):
        agent = self.agent(preview_then_text("p1", "方案。"))
        agent.run("退 1 件")
        confirmation_id = agent.create_confirmation()
        stored = store.get_confirmation(self.conn, confirmation_id)
        plan = agent.pending_plan
        self.assertEqual(stored["user_id"], USER)
        self.assertEqual(stored["plan"]["order_line_id"], plan["order_line_id"])
        self.assertEqual(stored["plan"]["quantity"], plan["quantity"])
        self.assertEqual(stored["policy_version"], plan["policy_version"])
        self.assertEqual(stored["plan_hash"], plan["plan_hash"])
        created = datetime.fromisoformat(stored["created_at"])
        expires = datetime.fromisoformat(stored["expires_at"])
        self.assertEqual(expires - created, timedelta(minutes=CONFIRMATION_TTL_MINUTES))

    def test_second_create_confirmation_invalidates_previous(self):
        agent = self.agent(preview_then_text("p1", "方案。"))
        agent.run("退 1 件")
        first_id = agent.create_confirmation()
        agent.create_confirmation()
        self.assertEqual(store.get_confirmation(self.conn, first_id)["status"], "invalid")
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM confirmations WHERE status = 'pending'"
        ).fetchone()[0]
        self.assertEqual(pending, 1)

    def test_submit_after_confirmation_creates_request_and_clears_plan(self):
        agent = self.agent(
            preview_then_text("p1", "方案。")
            + [
                tool_response("submit_return_request", {}, "s1"),
                text_response("已提交。"),
            ]
        )
        agent.run("退 1 件")
        before = store.get_order_line(self.conn, 101, USER)["reserved_qty"]
        agent.create_confirmation()
        result = agent.run("确认提交")
        [submitted] = [
            item for item in self.tool_results(agent.llm)
            if item["ok"] and item["data"].get("status") == "created"
        ]
        self.assertIn("submit_return_request", result["tools_used"])
        self.assertEqual(submitted["data"]["order_line_id"], 101)
        self.assertEqual(submitted["data"]["quantity"], 1)
        confirmation_id = self.conn.execute(
            "SELECT confirmation_id FROM return_requests WHERE request_id = ?",
            (submitted["data"]["request_id"],),
        ).fetchone()[0]
        request = store.get_return_request_by_confirmation(self.conn, confirmation_id)
        self.assertEqual(request["request_id"], submitted["data"]["request_id"])
        self.assertEqual(request["quantity"], 1)
        self.assertEqual(
            store.get_order_line(self.conn, 101, USER)["reserved_qty"], before + 1
        )
        self.assertIsNone(agent.pending_plan)
        self.assertIsNone(agent.confirmation_id)

    def test_text_only_after_confirmation_does_not_submit(self):
        agent = self.agent(preview_then_text("p1", "方案。") + [text_response("好的，我先不提交。")])
        agent.run("退 1 件")
        agent.create_confirmation()
        result = agent.run("确认提交")
        self.assertNotIn("submit_return_request", result["tools_used"])
        self.assertIsNotNone(agent.confirmation_id)

    def test_cancel_pending_invalidates_confirmation(self):
        agent = self.agent(preview_then_text("p1", "方案。"))
        agent.run("退 1 件")
        confirmation_id = agent.create_confirmation()
        agent.cancel_pending()
        self.assertEqual(store.get_confirmation(self.conn, confirmation_id)["status"], "invalid")
        self.assertIsNone(agent.pending_plan)
        self.assertIsNone(agent.confirmation_id)

    def test_submit_without_confirmation_is_rejected(self):
        agent = self.agent([
            tool_response("submit_return_request", {}, "s1"),
            text_response("现在没有可提交的确认。"),
        ])
        agent.run("确认提交")
        [result] = self.tool_results(agent.llm)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["error"]["category"], "business")
        self.assertEqual(result["error"]["code"], "NO_PENDING_CONFIRMATION")

    def test_second_submit_in_same_batch_is_idempotent(self):
        agent = self.agent(
            preview_then_text("p1", "方案。")
            + [
                calls_response(
                    make_call("submit_return_request", {}, "s1"),
                    make_call("submit_return_request", {}, "s2"),
                ),
                text_response("已提交。"),
            ]
        )
        agent.run("退 1 件")
        confirmation_id = agent.create_confirmation()
        agent.run("确认提交")
        statuses = [
            item["data"]["status"]
            for item in self.tool_results(agent.llm)
            if item["ok"] and "status" in item["data"]
        ]
        self.assertEqual(statuses, ["created", "already_exists"])
        count = self.conn.execute(
            "SELECT COUNT(*) FROM return_requests WHERE confirmation_id = ?",
            (confirmation_id,),
        ).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
