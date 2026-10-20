import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import store, tools
from .config import CONFIRMATION_TTL_MINUTES
from .llm import LLMError
from .tool_schemas import TOOL_SCHEMAS

MAX_TURNS = 8
MAX_TOOL_CALLS = 10
TIMEOUT_SECONDS = 60
MAX_CONSECUTIVE_TOOL_ERRORS = 3
LLM_CALL_TIMEOUT_SECONDS = 30
MAX_LLM_RETRIES = 2

# 修改此常量必须同步 docs/agent_flow.md §8
SYSTEM_PROMPT = (
    "你是退货申请助手，辅助用户进行退货。信息不足时要先澄清，不要猜。\n"
    "不能自行判断是否能退货，必须调用 `preview_return_request`。\n"
    "任何退货可行性判断（包括数量是否合法、是否超过可退数量）都必须由 `preview_return_request` 给出；不要根据 `query_orders` 的结果自行计算。\n"
    "即使用户给出的数量是 0、负数或明显超过购买数量，也必须先调用 `preview_return_request`；"
    "不得直接拒绝或自行判断。\n"
    "在 `submit` 未实现前，不能声称\"已提交\"，也不要承诺未来会开通提交功能。\n"
    "当用户明确表示确认提交、且当前存在已确认的方案时，必须调用 submit_return_request；"
    "不得用文字代替工具调用，也不得在未调用工具的情况下声称已提交。\n"
    "只能使用工具返回的事实，不能编造订单。\n"
    "用户提到订单号或订单行号时，必须与工具返回的 order_id / order_line_id 精确匹配；"
    "不得截断、改写或补零。匹配不到就明确说没有找到，不要用其他订单替代。\n"
    "不要提及不存在的官方渠道、App 或客服；只描述当前系统实际具备的能力。\n"
    "不确定的信息直接说明不确定。\n"
    "与用户交流使用中文，简洁明了。"
)

KNOWN_TOOLS = {
    "query_orders", "get_return_policy", "preview_return_request", "submit_return_request",
}

CLEAR_CONFIRMATION_CODES = {
    "PLAN_CHANGED", "POLICY_CHANGED", "CONFIRMATION_INVALID",
    "CONFIRMATION_EXPIRED", "CONFIRMATION_MISMATCH",
}


def _system_error(code, message):
    return {
        "ok": False,
        "data": None,
        "error": {"category": "system", "code": code, "message": message},
    }


def _summarize(result):
    if not result["ok"]:
        error = result["error"]
        return f"{error['category']}/{error['code']}"
    data = result["data"]
    if isinstance(data, list):
        return f"ok=true, {len(data)} rows"
    return "ok=true"


class Agent:
    max_turns = MAX_TURNS
    max_tool_calls = MAX_TOOL_CALLS
    timeout_seconds = TIMEOUT_SECONDS
    max_consecutive_tool_errors = MAX_CONSECUTIVE_TOOL_ERRORS
    llm_call_timeout_seconds = LLM_CALL_TIMEOUT_SECONDS
    max_llm_retries = MAX_LLM_RETRIES

    def __init__(self, llm, conn, current_user_id, tracer, system_prompt=SYSTEM_PROMPT,
                 clock=time.monotonic):
        self.llm = llm
        self.conn = conn
        self.current_user_id = current_user_id
        self.tracer = tracer
        self.clock = clock
        self.messages = [{"role": "system", "content": system_prompt}]
        self.pending_plan = None
        self.confirmation_id = None
        self._step = 0
        self._tools_used = []

    def _elapsed_ms(self, start):
        return int((self.clock() - start) * 1000)

    def create_confirmation(self):
        """把当前方案写成确认记录。无方案或写库失败时返回 None，不改动已有确认。"""
        if not self.pending_plan:
            return None
        confirmation_id = "c-" + uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        plan = self.pending_plan
        previous_id = self.confirmation_id
        try:
            with store.transaction(self.conn):
                if previous_id:
                    store.update_confirmation_status(self.conn, previous_id, "invalid")
                store.create_confirmation(
                    self.conn,
                    confirmation_id=confirmation_id,
                    user_id=self.current_user_id,
                    order_line_id=plan["order_line_id"],
                    quantity=plan["quantity"],
                    policy_version=plan["policy_version"],
                    plan_hash=plan["plan_hash"],
                    created_at=now.isoformat(),
                    expires_at=(now + timedelta(minutes=CONFIRMATION_TTL_MINUTES)).isoformat(),
                )
        except store.StoreError:
            return None
        self.confirmation_id = confirmation_id
        return confirmation_id

    def cancel_pending(self):
        if self.confirmation_id:
            try:
                with store.transaction(self.conn):
                    store.update_confirmation_status(self.conn, self.confirmation_id, "invalid")
            except store.StoreError:
                pass
        self.pending_plan = None
        self.confirmation_id = None

    def _clear_pending(self):
        self.pending_plan = None
        self.confirmation_id = None

    def run(self, user_message):
        self.messages.append({"role": "user", "content": user_message})
        self.tracer.user_message(self._step, user_message)
        self._started = self.clock()
        self._tools_used = []
        turns = 0
        tool_call_count = 0
        consecutive_errors = 0

        while True:
            if consecutive_errors >= self.max_consecutive_tool_errors:
                return self._stop("tool_errors", turns, tool_call_count,
                                  f"连续 {consecutive_errors} 次工具错误")
            if turns >= self.max_turns:
                return self._stop("max_turns", turns, tool_call_count)
            if tool_call_count >= self.max_tool_calls:
                return self._stop("max_tool_calls", turns, tool_call_count)

            turns += 1
            self._step += 1
            response, stop_reason, detail = self._call_model()
            if stop_reason is not None:
                return self._stop(stop_reason, turns, tool_call_count, detail)

            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                text = response.get("text") or ""
                self.messages.append({"role": "assistant", "content": text})
                self.tracer.assistant_message(self._step, text)
                return self._stop("final_answer", turns, tool_call_count, text=text)

            self.messages.append({
                "role": "assistant",
                "content": response.get("text"),
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call.get("arguments_raw") or "{}",
                        },
                    }
                    for call in tool_calls
                ],
            })

            budget_exceeded = False
            # 同一批里的第二次 submit 仍要看到本次确认，所以等整批执行完再清空。
            clear_pending = False
            for call in tool_calls:
                if tool_call_count >= self.max_tool_calls:
                    budget_exceeded = True
                    result = _system_error("TOOL_BUDGET_EXCEEDED", "本次请求的工具调用次数已达上限，未执行")
                    self._trace_tool(call, result, self.clock())
                else:
                    tool_call_count += 1
                    result, should_clear = self._execute(call)
                    clear_pending = clear_pending or should_clear
                    if not result["ok"] and result["error"]["category"] == "system":
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 0
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
            if clear_pending:
                self._clear_pending()
            if budget_exceeded:
                return self._stop("max_tool_calls", turns, tool_call_count)

    def _remaining(self):
        return self.timeout_seconds - (self.clock() - self._started)

    def _call_model(self):
        """返回 (response, stop_reason, detail)；成功时 stop_reason 为 None。"""
        attempts = 0
        while True:
            remaining = self._remaining()
            if remaining <= 0:
                return None, "timeout", None
            call_timeout = min(self.llm_call_timeout_seconds, remaining)
            started = self.clock()
            try:
                response = self.llm.chat(self.messages, TOOL_SCHEMAS, timeout=call_timeout)
            except LLMError as e:
                attempts += 1
                if self._remaining() > 0 and attempts <= self.max_llm_retries:
                    continue
                return None, "llm_error", str(e)
            self.tracer.model_call(
                self._step,
                getattr(self.llm, "model", None),
                response.get("usage"),
                self._elapsed_ms(started),
                response.get("finish_reason"),
            )
            return response, None, None

    def _execute(self, call):
        name = call.get("name")
        args = call.get("arguments")
        started = self.clock()

        self._tools_used.append(name)
        should_clear = False
        if name not in KNOWN_TOOLS:
            result = _system_error("INVALID_TOOL_CALL", f"未知工具：{name}")
        elif call.get("parse_error") or not isinstance(args, dict):
            result = _system_error("INVALID_TOOL_CALL", "工具参数无法解析")
        elif name == "query_orders":
            result = tools.query_orders(self.conn, self.current_user_id)
        elif name == "get_return_policy":
            result = tools.get_return_policy()
        elif name == "submit_return_request":
            result = tools.submit_return_request(
                self.conn, self.current_user_id, self.confirmation_id
            )
            status = (result.get("data") or {}).get("status")
            code = (result.get("error") or {}).get("code")
            if (result["ok"] and status in ("created", "already_exists")) or code in CLEAR_CONFIRMATION_CODES:
                should_clear = True
        else:
            result = tools.preview_return_request(
                self.conn,
                self.current_user_id,
                args.get("order_line_id"),
                args.get("quantity"),
            )
            if result["ok"] and self.confirmation_id:
                try:
                    with store.transaction(self.conn):
                        store.update_confirmation_status(
                            self.conn, self.confirmation_id, "invalid"
                        )
                except store.StoreError:
                    result = _system_error("TRANSACTION_FAILED", "旧确认无法失效，方案未更新")
                else:
                    self.pending_plan = result["data"]["plan"]
                    self.confirmation_id = None
            elif result["ok"]:
                self.pending_plan = result["data"]["plan"]
                self.confirmation_id = None

        self._trace_tool(call, result, started)
        return result, should_clear

    def _trace_tool(self, call, result, started):
        error = result["error"] or {}
        self.tracer.tool_call(
            self._step,
            call.get("name"),
            call.get("arguments"),
            "ok" if result["ok"] else "error",
            error.get("category"),
            error.get("code"),
            self._elapsed_ms(started),
            _summarize(result),
        )

    def _stop(self, reason, turns, tool_call_count, detail=None, text=None):
        self.tracer.stop(self._step, reason, None if reason == "final_answer" else detail)
        return {
            "text": text,
            "stop_reason": reason,
            "steps": turns,
            "tool_calls": tool_call_count,
            "tools_used": list(self._tools_used),
        }
