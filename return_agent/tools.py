import hashlib
from datetime import datetime, timezone

from . import store
from .policy import (
    POLICY_VERSION, WINDOW_DAYS, REQUIRE_DELIVERED, REQUIRE_RETURNABLE,
    QUANTITY_RULE, SUMMARY,
)
from .validation import OK, validate_return_request

FORBIDDEN_MESSAGE = "无法查询或操作该订单，请核对订单信息。"

REJECTION_MESSAGES = {
    "FORBIDDEN": FORBIDDEN_MESSAGE,
    "NOT_DELIVERED": "商品尚未收货，暂不能申请退货。",
    "INVALID_INPUT": "订单数据异常，暂不能申请退货。",
    "WINDOW_EXPIRED": "已超过退货期限，不能申请退货。",
    "ITEM_NOT_RETURNABLE": "该商品不支持退货。",
    "INVALID_QUANTITY": "退货数量必须是正整数。",
    "INSUFFICIENT_QUANTITY": "申请数量超过剩余可退数量。",
}


def _ok(data):
    return {"ok": True, "data": data, "error": None}


def _error(category, code, message):
    return {
        "ok": False,
        "data": None,
        "error": {"category": category, "code": code, "message": message},
    }


def _is_valid_identity(current_user_id):
    return isinstance(current_user_id, str) and current_user_id.strip() != ""


def query_orders(conn, current_user_id):
    """查当前身份下的订单行；current_user_id 由执行器注入。"""
    if not _is_valid_identity(current_user_id):
        return _error("input", "INVALID_IDENTITY", "注入身份无效")
    try:
        lines = store.list_order_lines(conn, current_user_id)
    except store.StoreTimeout:
        return _error("system", "TIMEOUT", "订单存储响应超时")
    except store.StoreError:
        return _error("system", "STORE_UNAVAILABLE", "订单存储暂不可用")
    return _ok(lines)


def get_return_policy():
    """读取演示退货规则及其版本号。

    规则当前为本地常量，本函数不会失败；契约中的 POLICY_UNAVAILABLE 暂不可达，
    保留给将来规则改为配置或存储时使用。
    """
    return _ok({
        "version": POLICY_VERSION,
        "window_days": WINDOW_DAYS,
        "requires_delivered": REQUIRE_DELIVERED,
        "requires_returnable": REQUIRE_RETURNABLE,
        "quantity_rule": QUANTITY_RULE,
        "summary": SUMMARY,
    })


def compute_plan_hash(order_line, quantity):
    """预览与提交必须共用此函数，字段顺序与序列化方式不得改变。"""
    payload = "|".join(str(value) for value in (
        order_line["order_line_id"],
        quantity,
        int(bool(order_line["status"])),
        order_line["days_since_delivery"],
        int(bool(order_line["returnable"])),
        order_line["purchased_qty"],
        order_line["reserved_qty"],
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preview_return_request(conn, current_user_id, order_line_id, quantity):
    """校验并生成退货申请方案，不写入任何数据；current_user_id 由执行器注入。"""
    if not _is_valid_identity(current_user_id):
        return _error("input", "INVALID_IDENTITY", "注入身份无效")
    if not isinstance(order_line_id, int) or isinstance(order_line_id, bool):
        return _error("input", "INVALID_ARGUMENT", "order_line_id 必须是整数")

    try:
        order_line = store.get_order_line(conn, order_line_id, current_user_id)
    except store.StoreTimeout:
        return _error("system", "TIMEOUT", "订单存储响应超时")
    except store.StoreError:
        return _error("system", "STORE_UNAVAILABLE", "订单存储暂不可用")
    if order_line is None:
        return _error("business", "FORBIDDEN", FORBIDDEN_MESSAGE)

    # store 已按 owner_id 过滤且不返回该字段；validate_return_request 需要它。
    result = validate_return_request(
        current_user_id, {**order_line, "owner_id": current_user_id}, quantity
    )
    reason_code = result["reason_code"]
    if reason_code != OK:
        return _error("business", reason_code, REJECTION_MESSAGES.get(reason_code, "暂时无法判断"))

    plan = {
        "order_line_id": order_line_id,
        "quantity": quantity,
        "policy_version": POLICY_VERSION,
        "plan_hash": compute_plan_hash(order_line, quantity),
    }
    summary = f"订单行 {order_line_id}，退货数量 {quantity}（规则版本 {POLICY_VERSION}）"
    return _ok({"allowed": True, "plan": plan, "summary": summary})


CONFIRMATION_MESSAGES = {
    "NO_PENDING_CONFIRMATION": "当前没有待确认的退货方案。",
    "CONFIRMATION_MISMATCH": "无法提交该确认，请重新预览。",
    "CONFIRMATION_INVALID": "该确认已失效，请重新预览。",
    "CONFIRMATION_EXPIRED": "该确认已过期，请重新预览。",
    "PLAN_CHANGED": "订单信息已变化，请重新预览。",
    "POLICY_CHANGED": "退货规则已更新，请重新预览。",
}


def _business(code):
    message = CONFIRMATION_MESSAGES.get(code) or REJECTION_MESSAGES.get(code, "暂时无法判断")
    return _error("business", code, message)


def _as_utc(text):
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def submit_return_request(conn, current_user_id, confirmation_id):
    """提交执行器注入的确认。confirmation_id 不能由模型指定。"""
    if not _is_valid_identity(current_user_id):
        return _error("input", "INVALID_IDENTITY", "注入身份无效")
    if confirmation_id is None or (
        isinstance(confirmation_id, str) and confirmation_id.strip() == ""
    ):
        return _business("NO_PENDING_CONFIRMATION")

    try:
        with store.transaction(conn):
            confirmation = store.get_confirmation(conn, confirmation_id)
            if confirmation is None:
                return _business("NO_PENDING_CONFIRMATION")
            if confirmation["user_id"] != current_user_id:
                return _business("CONFIRMATION_MISMATCH")

            plan = confirmation["plan"]
            order_line_id = plan["order_line_id"]
            quantity = plan["quantity"]

            if confirmation["status"] == "used":
                return _ok({
                    "request_id": confirmation["request_id"],
                    "status": "already_exists",
                    "order_line_id": order_line_id,
                    "quantity": quantity,
                })
            if confirmation["status"] == "invalid":
                return _business("CONFIRMATION_INVALID")

            if confirmation["status"] == "expired" or datetime.now(timezone.utc) > _as_utc(
                confirmation["expires_at"]
            ):
                store.update_confirmation_status(conn, confirmation_id, "expired")
                return _business("CONFIRMATION_EXPIRED")

            order_line = store.get_order_line(conn, order_line_id, current_user_id)
            if order_line is None:
                store.update_confirmation_status(conn, confirmation_id, "invalid")
                return _business("PLAN_CHANGED")
            if compute_plan_hash(order_line, quantity) != confirmation["plan_hash"]:
                store.update_confirmation_status(conn, confirmation_id, "invalid")
                return _business("PLAN_CHANGED")
            if confirmation["policy_version"] != POLICY_VERSION:
                store.update_confirmation_status(conn, confirmation_id, "invalid")
                return _business("POLICY_CHANGED")

            verdict = validate_return_request(
                current_user_id, {**order_line, "owner_id": current_user_id}, quantity
            )
            reason_code = verdict["reason_code"]
            if reason_code != OK:
                store.update_confirmation_status(conn, confirmation_id, "invalid")
                return _error(
                    "business",
                    reason_code,
                    REJECTION_MESSAGES.get(reason_code, "暂时无法判断"),
                )

            request_id = store.create_return_request(
                conn,
                owner_id=current_user_id,
                order_line_id=order_line_id,
                quantity=quantity,
                policy_version=confirmation["policy_version"],
                confirmation_id=confirmation_id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            store.increment_reserved(conn, order_line_id, quantity)
            store.update_confirmation_status(conn, confirmation_id, "used", request_id)
            return _ok({
                "request_id": request_id,
                "status": "created",
                "order_line_id": order_line_id,
                "quantity": quantity,
            })
    except store.StoreTimeout:
        return _error("system", "TIMEOUT", "订单存储响应超时")
    except store.StoreError:
        return _error("system", "TRANSACTION_FAILED", "提交失败，未产生申请或数量占用")
