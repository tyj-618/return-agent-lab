import copy
import json
import os
import tempfile
import unittest

from return_agent import policy, store
from return_agent.agent import Agent
from return_agent.config import CONFIRMATION_TTL_MINUTES
from return_agent.session import ChatSession
from return_agent.tools import compute_plan_hash
from return_agent.trace import Tracer

USER = "U001"
USAGE = {"prompt_tokens": 1, "completion_tokens": 1}


def tool_response(name, arguments, call_id="call_1"):
    return {
        "text": None,
        "tool_calls": [{
            "id": call_id,
            "name": name,
            "arguments": arguments,
            "arguments_raw": json.dumps(arguments),
        }],
        "finish_reason": "tool_calls",
        "usage": USAGE,
    }


def text_response(text):
    return {"text": text, "tool_calls": [], "finish_reason": "stop", "usage": USAGE}


class ScriptedLLM:
    model = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.received = []

    def chat(self, messages, tools, timeout=None):
        self.received.append(copy.deepcopy(messages))
        index = min(len(self.received) - 1, len(self.responses) - 1)
        return copy.deepcopy(self.responses[index])


class ChatSessionTest(unittest.TestCase):
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

    def session(self, responses):
        agent = Agent(ScriptedLLM(responses), self.conn, USER, self.tracer)
        return ChatSession(agent), agent

    def valid_plan(self):
        line = store.get_order_line(self.conn, 101, USER)
        return {
            "order_line_id": 101,
            "quantity": 1,
            "policy_version": policy.POLICY_VERSION,
            "plan_hash": compute_plan_hash(line, 1),
        }

    def confirmation_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0]

    def test_confirm_without_plan_is_blocked(self):
        session, _ = self.session([])
        before = self.confirmation_count()
        resp = session.handle("确认提交")
        self.assertEqual(resp["kind"], "confirm_blocked")
        self.assertEqual(resp["text"], "当前没有可确认的方案，请先让我为你生成方案。")
        self.assertIsNone(resp["hint"])
        self.assertEqual(self.confirmation_count(), before)

    def test_confirm_with_submit_has_no_hint(self):
        session, agent = self.session([
            tool_response("submit_return_request", {}),
            text_response("已提交。"),
        ])
        agent.pending_plan = self.valid_plan()
        resp = session.handle("确认提交")
        self.assertEqual(resp["kind"], "confirm_created")
        self.assertEqual(resp["text"], "已提交。")
        self.assertIsNone(resp["hint"])

    def test_confirm_without_submit_has_hint(self):
        session, agent = self.session([text_response("好的，我先不提交。")])
        agent.pending_plan = self.valid_plan()
        resp = session.handle("  确认提交  ")
        self.assertEqual(resp["kind"], "confirm_created")
        self.assertEqual(resp["hint"], f"（未提交，确认将在 {CONFIRMATION_TTL_MINUTES} 分钟后失效。）")

    def test_cancel_invalidates_confirmation(self):
        session, agent = self.session([])
        agent.pending_plan = self.valid_plan()
        confirmation_id = agent.create_confirmation()
        resp = session.handle("取消")
        self.assertEqual(resp["kind"], "cancel")
        self.assertEqual(resp["text"], "已取消，未提交任何退货申请。")
        self.assertIsNone(resp["hint"])
        stored = store.get_confirmation(self.conn, confirmation_id)
        self.assertEqual(stored["status"], "invalid")
        self.assertIsNone(agent.pending_plan)
        self.assertIsNone(agent.confirmation_id)


if __name__ == "__main__":
    unittest.main()
