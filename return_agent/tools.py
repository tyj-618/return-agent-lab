from . import store
from .policy import (
    POLICY_VERSION, WINDOW_DAYS, REQUIRE_DELIVERED, REQUIRE_RETURNABLE,
    QUANTITY_RULE, SUMMARY,
)


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
    except store.StoreError:
        return _error("system", "STORE_UNAVAILABLE", "订单存储暂不可用，暂时无法查询")
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
