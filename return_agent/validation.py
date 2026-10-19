from .policy import WINDOW_DAYS

OK = "OK"
FORBIDDEN = "FORBIDDEN"
NOT_DELIVERED = "NOT_DELIVERED"
INVALID_INPUT = "INVALID_INPUT"
WINDOW_EXPIRED = "WINDOW_EXPIRED"
ITEM_NOT_RETURNABLE = "ITEM_NOT_RETURNABLE"
INVALID_QUANTITY = "INVALID_QUANTITY"
INSUFFICIENT_QUANTITY = "INSUFFICIENT_QUANTITY"

REASON_CODES = frozenset({
    OK,
    FORBIDDEN,
    NOT_DELIVERED,
    INVALID_INPUT,
    WINDOW_EXPIRED,
    ITEM_NOT_RETURNABLE,
    INVALID_QUANTITY,
    INSUFFICIENT_QUANTITY,
})


def _result(reason_code):
    return {"allowed": reason_code == OK, "reason_code": reason_code}


def validate_return_request(current_user_id, order_line, quantity):
    if not isinstance(current_user_id, str) or current_user_id.strip() == "":
        return _result(INVALID_INPUT)
    if order_line["owner_id"] != current_user_id:
        return _result(FORBIDDEN)
    if order_line["status"] is not True:
        return _result(NOT_DELIVERED)

    days = order_line["days_since_delivery"]
    if days < 0:
        return _result(INVALID_INPUT)
    if days > WINDOW_DAYS:
        return _result(WINDOW_EXPIRED)

    if order_line["returnable"] is not True:
        return _result(ITEM_NOT_RETURNABLE)

    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return _result(INVALID_QUANTITY)
    if quantity > order_line["purchased_qty"] - order_line["reserved_qty"]:
        return _result(INSUFFICIENT_QUANTITY)

    return _result(OK)
