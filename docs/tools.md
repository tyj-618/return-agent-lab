# 内部校验函数 validate_return_request

它不是四个 Agent 工具的实现，也不是完整业务验收。

## 范围

`status`、`returnable`、`quantity` 的类型违规在本函数内显式处理；`owner_id`、`days_since_delivery`、`purchased_qty`、`reserved_qty` 的类型与取值符合 data_model.md。字段缺失时按 Python 直接访问字典键处理（KeyError），不额外做防护或默认值。仅含空白的身份字符串视为无效输入（INVALID_INPUT）；其余仍按普通字符串严格相等比较。

## 函数契约

```text
validate_return_request(current_user_id, order_line, quantity) -> dict
```

- 只读 `order_line`，不修改入参。
- `reason_code` 只能是：`OK`、`FORBIDDEN`、`NOT_DELIVERED`、`INVALID_INPUT`、`WINDOW_EXPIRED`、`ITEM_NOT_RETURNABLE`、`INVALID_QUANTITY`、`INSUFFICIENT_QUANTITY`。
- 返回值只有 `allowed`、`reason_code` 两个键，不返回他人订单详情、剩余可退数量或其他字段。
- 命中第一条失败即返回，后续条件不再判断。
- 本函数严格要求布尔值；若上游存储返回 `0`/`1`，由工具边界负责转换，本函数不处理。

## 判定顺序

1. `current_user_id` 不是非空 `str` → `INVALID_INPUT`
2. `order_line["owner_id"] != current_user_id` → `FORBIDDEN`
3. `order_line["status"] is not True` → `NOT_DELIVERED`
4. `order_line["days_since_delivery"] < 0` → `INVALID_INPUT`
5. `order_line["days_since_delivery"] > 14` → `WINDOW_EXPIRED`（`0` 与 `14` 均有效）
6. `order_line["returnable"] is not True` → `ITEM_NOT_RETURNABLE`
7. `quantity` 的类型不是 `int`、或是 `bool`、或 `quantity <= 0` → `INVALID_QUANTITY`
8. `quantity > purchased_qty - reserved_qty` → `INSUFFICIENT_QUANTITY`
9. 否则 → `{"allowed": True, "reason_code": "OK"}`

失败时 `allowed` 为 `False`。`status`、`returnable` 用 `is True`，不把其他真值当作通过。
