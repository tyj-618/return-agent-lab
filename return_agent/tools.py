import hashlib

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
