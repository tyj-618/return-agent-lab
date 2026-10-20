import re
import uuid
from datetime import datetime, timedelta, timezone

from return_agent import store, tools
from return_agent.config import CONFIRMATION_TTL_MINUTES

PREVIEW_TEXT = {
    "FORBIDDEN": "无法查询或操作该订单，请核对订单信息。",
    "WINDOW_EXPIRED": "已超过退货期限（14 天），不能申请退货。",
    "NOT_DELIVERED": "商品尚未收货，暂不能申请退货。",
    "ITEM_NOT_RETURNABLE": "该商品不支持退货。",
    "INVALID_QUANTITY": "退货数量必须是正整数。",
    "INSUFFICIENT_QUANTITY": "申请数量超过剩余可退数量。",
}

LINE_ID = re.compile(r"订单行\s*(\d+)")
ORDER_ID = re.compile(r"订单\s*(\d+)")
QUANTITY = re.compile(r"(\d+)\s*件")


def _tool_event(name, args, result):
    error = result.get("error") or {}
    return {
        "type": "tool",
        "name": name,
        "args": args,
        "status": "ok" if result["ok"] else "error",
        "category": error.get("category"),
        "code": error.get("code"),
    }


class FixedFlow:
    """按正则和工具调用走固定退货流程，不使用模型。"""

    def __init__(self, conn, current_user_id):
        self.conn = conn
        self.current_user_id = current_user_id
        self.pending = None
        self.events = []

    def handle(self, text):
        message = text.strip()
        if message == "确认提交":
            response = self._confirm()
        elif message == "取消":
            self.pending = None
            response = {"text": "已取消。", "kind": "cancel"}
        else:
            response = self._request(message)
        response["events"] = list(self.events)
        return response

    def _confirm(self):
        if not self.pending:
            return {"text": "当前没有可确认的方案。", "kind": "confirm_blocked"}
        plan = self.pending
        confirmation_id = "b-" + uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        try:
            with store.transaction(self.conn):
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
            return {"text": "暂时无法处理。", "kind": "confirm_blocked"}
        result = tools.submit_return_request(self.conn, self.current_user_id, confirmation_id)
        self.events.append(_tool_event("submit_return_request", {}, result))
        if result["ok"] and result["data"]["status"] == "created":
            self.pending = None
            return {
                "text": f"提交成功，申请编号 {result['data']['request_id']}",
                "kind": "confirm_created",
            }
        if result["ok"] and result["data"]["status"] == "already_exists":
            self.pending = None
            return {"text": "该申请已提交", "kind": "confirm_created"}
        return {"text": "暂时无法处理。", "kind": "confirm_created"}

    def _request(self, message):
        listed = tools.query_orders(self.conn, self.current_user_id)
        self.events.append(_tool_event("query_orders", {}, listed))
        if not listed["ok"]:
            return {"text": "暂时无法处理。", "kind": "chat"}

        line_match = LINE_ID.search(message)
        order_match = ORDER_ID.search(message)
        qty_match = QUANTITY.search(message)
        line_id = int(line_match.group(1)) if line_match else None
        order_id = int(order_match.group(1)) if order_match else None
        qty = int(qty_match.group(1)) if qty_match else None

        if line_id is None:
            candidates = [
                line for line in listed["data"] if order_id is not None and line["order_id"] == order_id
            ]
            if not candidates:
                return {"text": "没有找到该订单。", "kind": "chat"}
            named = [line for line in candidates if line["product_name"] in message]
            if named:
                line_id = named[0]["order_line_id"]
            elif len(candidates) == 1:
                line_id = candidates[0]["order_line_id"]
            else:
                return {"text": "请提供订单号和退货数量。", "kind": "chat"}
        if qty is None:
            return {"text": "请提供退货数量。", "kind": "chat"}

        preview = tools.preview_return_request(self.conn, self.current_user_id, line_id, qty)
        self.events.append(_tool_event(
            "preview_return_request",
            {"order_line_id": line_id, "quantity": qty},
            preview,
        ))
        if preview["ok"]:
            self.pending = preview["data"]["plan"]
            return {"text": f"校验通过：订单行 {line_id}，退货数量 {qty}。", "kind": "chat"}
        code = preview["error"]["code"]
        return {"text": PREVIEW_TEXT.get(code, "暂时无法处理。"), "kind": "chat"}
