import copy
import json
import os
import tempfile
import unittest

from return_agent import store
from return_agent.agent import MAX_TURNS, Agent
from return_agent.llm import LLMError
from return_agent.trace import Tracer

USAGE = {"prompt_tokens": 10, "completion_tokens": 5}


def make_call(name, arguments, call_id="call_1", raw=None, parse_error=False):
    call = {
        "id": call_id,
        "name": name,
        "arguments": arguments,
        "arguments_raw": raw if raw is not None else json.dumps(arguments),
    }
    if parse_error:
        call["parse_error"] = True
    return call


def calls_response(*calls):
    return {"text": None, "tool_calls": list(calls), "finish_reason": "tool_calls", "usage": USAGE}


def tool_response(name, arguments, **kwargs):
    return calls_response(make_call(name, arguments, **kwargs))


def text_response(text):
    return {"text": text, "tool_calls": [], "finish_reason": "stop", "usage": USAGE}


class ScriptedLLM:
    """按顺序返回预设响应；脚本用完后重复最后一条。记录每次收到的 messages 与 timeout。"""

    model = "scripted"

    def __init__(self, responses, on_call=None):
        self.responses = list(responses)
        self.on_call = on_call
        self.received = []
        self.timeouts = []

    def chat(self, messages, tools, timeout=None):
        self.received.append(copy.deepcopy(messages))
        self.timeouts.append(timeout)
        if self.on_call:
            self.on_call(len(self.received))
        index = min(len(self.received) - 1, len(self.responses) - 1)
        return copy.deepcopy(self.responses[index])


class FailingLLM:
    model = "failing"

    def __init__(self, on_call=None):
        self.calls = 0
        self.on_call = on_call

    def chat(self, messages, tools, timeout=None):
        self.calls += 1
        if self.on_call:
            self.on_call(self.calls)
        raise LLMError("模型调用失败：APITimeoutError")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def seeded_conn():
    conn = store.connect(":memory:")
    store.init_schema(conn)
    store.seed_demo_data(conn)
    return conn


def tool_messages(messages):
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


class AgentLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trace_path = os.path.join(self.tmp.name, "test-run.jsonl")
        self.tracer = Tracer(self.trace_path)
        self.conn = seeded_conn()

    def tearDown(self):
        self.tracer.close()
        self.conn.close()
        self.tmp.cleanup()

    def read_trace(self):
        self.tracer.close()
        with open(self.trace_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_preview_then_final_answer(self):
        llm = ScriptedLLM([
            tool_response("preview_return_request", {"order_line_id": 101, "quantity": 1}),
            text_response("可以退货，方案如下。"),
        ])
        result = Agent(llm, self.conn, "U001", self.tracer).run("我想退 1 件蓝色 T 恤")

        self.assertEqual(result["stop_reason"], "final_answer")
        self.assertEqual(result["text"], "可以退货，方案如下。")
        self.assertEqual(result["tool_calls"], 1)
        [tool_result] = tool_messages(llm.received[1])
        self.assertIs(tool_result["ok"], True)
        self.assertEqual(tool_result["data"]["plan"]["order_line_id"], 101)
        types = [event["type"] for event in self.read_trace()]
        self.assertEqual(types, ["user", "model", "tool", "model", "assistant", "stop"])

    def test_stops_at_max_turns(self):
        llm = ScriptedLLM([tool_response("query_orders", {})])
        result = Agent(llm, self.conn, "U001", self.tracer).run("查订单")
        self.assertEqual(result["stop_reason"], "max_turns")
        self.assertEqual(result["steps"], MAX_TURNS)
        self.assertEqual(len(llm.received), MAX_TURNS)

    def test_stops_at_max_tool_calls(self):
        class SmallAgent(Agent):
            max_tool_calls = 3

        llm = ScriptedLLM([tool_response("query_orders", {})])
        result = SmallAgent(llm, self.conn, "U001", self.tracer).run("查订单")
        self.assertEqual(result["stop_reason"], "max_tool_calls")
        self.assertEqual(result["tool_calls"], 3)

    def test_tool_budget_fills_every_call_in_batch(self):
        class SmallAgent(Agent):
            max_tool_calls = 3

        llm = ScriptedLLM([calls_response(
            make_call("query_orders", {}, call_id="a"),
            make_call("get_return_policy", {}, call_id="b"),
        )])
        agent = SmallAgent(llm, self.conn, "U001", self.tracer)
        result = agent.run("查订单和规则")

        self.assertEqual(result["stop_reason"], "max_tool_calls")
        self.assertEqual(result["tool_calls"], 3)
        requested = [
            call["id"]
            for m in agent.messages if m["role"] == "assistant"
            for call in m.get("tool_calls", [])
        ]
        answered = [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"]
        self.assertEqual(requested, ["a", "b", "a", "b"])
        self.assertEqual(answered, requested)
        last = json.loads(agent.messages[-1]["content"])
        self.assertEqual(last["error"]["code"], "TOOL_BUDGET_EXCEEDED")
        self.assertEqual(last["error"]["category"], "system")

    def test_stops_after_consecutive_system_errors(self):
        broken = seeded_conn()
        broken.close()
        llm = ScriptedLLM([tool_response("query_orders", {})])
        result = Agent(llm, broken, "U001", self.tracer).run("查订单")
        self.assertEqual(result["stop_reason"], "tool_errors")
        self.assertEqual(result["tool_calls"], 3)
        codes = [e["code"] for e in self.read_trace() if e["type"] == "tool"]
        self.assertEqual(codes, ["STORE_UNAVAILABLE"] * 3)

    def test_business_rejection_does_not_count_as_tool_error(self):
        llm = ScriptedLLM([
            tool_response("preview_return_request", {"order_line_id": 501, "quantity": 1})
        ])
        result = Agent(llm, self.conn, "U001", self.tracer).run("退 501")
        self.assertEqual(result["stop_reason"], "max_turns")

    def test_unknown_tool_is_reported_to_model_and_loop_continues(self):
        llm = ScriptedLLM([
            tool_response("nope", {}),
            text_response("抱歉，我无法执行该操作。"),
        ])
        result = Agent(llm, self.conn, "U001", self.tracer).run("随便做点什么")
        self.assertEqual(result["stop_reason"], "final_answer")
        [tool_result] = tool_messages(llm.received[1])
        self.assertIs(tool_result["ok"], False)
        self.assertEqual(tool_result["error"]["category"], "system")
        self.assertEqual(tool_result["error"]["code"], "INVALID_TOOL_CALL")

    def test_unknown_tool_counts_as_consecutive_error(self):
        llm = ScriptedLLM([tool_response("nope", {})])
        result = Agent(llm, self.conn, "U001", self.tracer).run("随便做点什么")
        self.assertEqual(result["stop_reason"], "tool_errors")
        self.assertEqual(result["tool_calls"], 3)

    def test_unparseable_arguments_are_reported_to_model(self):
        llm = ScriptedLLM([
            tool_response("preview_return_request", None, raw="{bad json", parse_error=True),
            text_response("请再告诉我订单行和数量。"),
        ])
        result = Agent(llm, self.conn, "U001", self.tracer).run("退货")
        self.assertEqual(result["stop_reason"], "final_answer")
        [tool_result] = tool_messages(llm.received[1])
        self.assertEqual(tool_result["error"]["code"], "INVALID_TOOL_CALL")

    def test_history_keeps_raw_arguments(self):
        raw = '{ "order_line_id":101,  "quantity": 1 }'
        llm = ScriptedLLM([
            tool_response(
                "preview_return_request", {"order_line_id": 101, "quantity": 1}, raw=raw
            ),
            text_response("好的。"),
        ])
        agent = Agent(llm, self.conn, "U001", self.tracer)
        agent.run("退 101")
        [assistant] = [m for m in llm.received[1] if m["role"] == "assistant"]
        self.assertEqual(assistant["tool_calls"][0]["function"]["arguments"], raw)

    def test_model_supplied_identity_is_ignored(self):
        llm = ScriptedLLM([
            tool_response(
                "preview_return_request",
                {"order_line_id": 501, "quantity": 1, "current_user_id": "U002"},
            ),
            text_response("无法操作该订单。"),
        ])
        Agent(llm, self.conn, "U001", self.tracer).run("退 501")
        [tool_result] = tool_messages(llm.received[1])
        self.assertEqual(tool_result["error"]["code"], "FORBIDDEN")

    def test_timeout_before_second_model_call(self):
        clock = FakeClock()

        def advance(call_number):
            if call_number == 1:
                clock.now += 61

        llm = ScriptedLLM([tool_response("query_orders", {})], on_call=advance)
        result = Agent(llm, self.conn, "U001", self.tracer, clock=clock).run("查订单")
        self.assertEqual(result["stop_reason"], "timeout")
        self.assertEqual(len(llm.received), 1)

    def test_call_timeout_is_capped_by_remaining_budget(self):
        clock = FakeClock()

        def advance(call_number):
            clock.now += 45

        llm = ScriptedLLM(
            [tool_response("query_orders", {}), text_response("好的。")], on_call=advance
        )
        Agent(llm, self.conn, "U001", self.tracer, clock=clock).run("查订单")
        self.assertEqual(llm.timeouts, [30, 15])

    def test_llm_error_after_retries_exhausted(self):
        llm = FailingLLM()
        result = Agent(llm, self.conn, "U001", self.tracer).run("查订单")
        self.assertEqual(result["stop_reason"], "llm_error")
        self.assertEqual(llm.calls, 3)
        [stop] = [e for e in self.read_trace() if e["type"] == "stop"]
        self.assertEqual(stop["reason"], "llm_error")

    def test_llm_error_without_retry_when_time_budget_exhausted(self):
        clock = FakeClock()

        def advance(call_number):
            clock.now += 61

        llm = FailingLLM(on_call=advance)
        result = Agent(llm, self.conn, "U001", self.tracer, clock=clock).run("查订单")
        self.assertEqual(result["stop_reason"], "llm_error")
        self.assertEqual(llm.calls, 1)

    def test_trace_lines_are_json_with_required_fields(self):
        llm = ScriptedLLM([
            tool_response("query_orders", {}),
            text_response("你有 7 个订单行。"),
        ])
        Agent(llm, self.conn, "U001", self.tracer).run("查订单")
        events = self.read_trace()
        self.assertTrue(events)
        for event in events:
            for field in ("ts", "run_id", "step", "type"):
                self.assertIn(field, event)
            self.assertEqual(event["run_id"], "test-run")
            self.assertIn(event["type"], {"user", "model", "tool", "assistant", "stop"})

    def test_trace_records_user_and_assistant_text(self):
        llm = ScriptedLLM([
            tool_response("query_orders", {}),
            text_response("你有 7 个订单行。"),
        ])
        Agent(llm, self.conn, "U001", self.tracer).run("帮我查一下订单")
        events = self.read_trace()
        users = [e for e in events if e["type"] == "user"]
        assistants = [e for e in events if e["type"] == "assistant"]
        self.assertEqual([e["text"] for e in users], ["帮我查一下订单"])
        self.assertEqual(len(assistants), 1)
        self.assertTrue(assistants[0]["text"])
        self.assertEqual(assistants[0]["text"], "你有 7 个订单行。")


if __name__ == "__main__":
    unittest.main()
