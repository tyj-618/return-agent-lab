# 工具契约

本文件定义内部校验函数与 Agent 工具契约；引用 docs/data_model.md，不重复定义字段；验收案例见 docs/acceptance.md。

## 统一返回封装

成功：{"ok": true, "data": <结果>, "error": null}

失败：{"ok": false, "data": null, "error": {"category": "input|business|system", "code": "...", "message": "..."}}

工具参数分「模型可见参数」与「执行器注入参数」；身份只允许走注入。

**统一注入身份校验**：凡使用 `current_user_id` 的工具（query_orders、preview_return_request、submit_return_request），注入身份必须是 `strip()` 后非空字符串；否则返回 `{"ok": false, "data": null, "error": {"category": "input", "code": "INVALID_IDENTITY", "message": "..."}}`。

**错误码分层**：
- input：`INVALID_IDENTITY`、`INVALID_ARGUMENT`
- business：`FORBIDDEN`、`NOT_DELIVERED`、`INVALID_INPUT`、`WINDOW_EXPIRED`、`ITEM_NOT_RETURNABLE`、`INVALID_QUANTITY`、`INSUFFICIENT_QUANTITY`、`NO_PENDING_CONFIRMATION`、`CONFIRMATION_MISMATCH`、`CONFIRMATION_INVALID`、`CONFIRMATION_EXPIRED`、`PLAN_CHANGED`、`POLICY_CHANGED`
- system：`STORE_UNAVAILABLE`、`TIMEOUT`、`TRANSACTION_FAILED`、`POLICY_UNAVAILABLE`

备注：执行器可能合成 `system / INVALID_TOOL_CALL` 与 `system / TOOL_BUDGET_EXCEEDED`（不属于四工具自身返回）。

## 内部校验函数 validate_return_request

它不是四个 Agent 工具的实现，也不是完整业务验收。

### 范围

`status`、`returnable`、`quantity` 的类型违规在本函数内显式处理；`owner_id`、`days_since_delivery`、`purchased_qty`、`reserved_qty` 的类型与取值符合 data_model.md。字段缺失时按 Python 直接访问字典键处理（KeyError），不额外做防护或默认值。仅含空白的身份字符串视为无效输入（INVALID_INPUT）；其余仍按普通字符串严格相等比较。

### 函数契约

```text
validate_return_request(current_user_id, order_line, quantity) -> dict
```

- 只读 `order_line`，不修改入参。
- `reason_code` 只能是：`OK`、`FORBIDDEN`、`NOT_DELIVERED`、`INVALID_INPUT`、`WINDOW_EXPIRED`、`ITEM_NOT_RETURNABLE`、`INVALID_QUANTITY`、`INSUFFICIENT_QUANTITY`。
- 返回值只有 `allowed`、`reason_code` 两个键，不返回他人订单详情、剩余可退数量或其他字段。
- 命中第一条失败即返回，后续条件不再判断。
- 本函数严格要求布尔值；若上游存储返回 `0`/`1`，由工具边界负责转换，本函数不处理。

### 判定顺序

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

## Agent 工具

### query_orders

- **用途**：查当前身份下的订单行。
- **输入（模型可见）**：无。
- **注入（执行器）**：`current_user_id` —— 来自可信会话，模型不可指定、不可见。
- **输出（成功）**：`{"ok": true, "data": [订单行...], "error": null}`

  订单行字段：`order_id`、`order_line_id`、`product_name`、`status`、`days_since_delivery`、`returnable`、`purchased_qty`、`reserved_qty`。

  - 不返回 `owner_id`（等于当前身份，冗余）。
  - 不返回派生值（如剩余可退数量、最终能否退货）；这些由 `preview_return_request` 计算。

- **输出（失败）**：`{"ok": false, "data": null, "error": {"category": "input|business|system", "code": "...", "message": "..."}}`
- **前置条件**：注入身份为 `strip()` 后非空的字符串。
- **错误**：

  | 类别 | 条件 | code |
  | --- | --- | --- |
  | 输入非法 | 注入身份为空 / 仅空白 / 非字符串（接线错误，不是用户输入问题） | `INVALID_IDENTITY` |
  | 业务拒绝 | 无（查不到就是空列表，不报错） | — |
  | 系统失败 | 存储不可用 | `STORE_UNAVAILABLE` |
  | 系统失败 | 查询超时 | `TIMEOUT` |

- **副作用**：无（只读）。
- **边界**：
  - 只返回该身份的订单行，不返回他人数据；
  - 不修改任何数据；
  - 返回全部订单行（含未收货、不可退），是否可退由 `preview_return_request` 判断；
  - 结果按 `(order_id, order_line_id)` 升序排序，保证同一订单多行时顺序稳定。
- **备注**：查询不到订单时返回 `ok=true, data=[]`，由 Agent 决定如何向用户说明。

### get_return_policy

- **用途**：读取演示退货规则及其版本号，用于向用户解释规则；不用于判定。
- **输入（模型可见）**：无。
- **注入（执行器）**：无（不依赖身份）。
- **输出（成功）**：`{"ok": true, "data": {"version": "policy-v1", "window_days": 14, "requires_delivered": true, "requires_returnable": true, "quantity_rule": "quantity <= purchased_qty - reserved_qty", "summary": "已收货商品在收货后 0–14 个完整天内可申请退货；商品需支持退货；数量不超过剩余可退数量。"}, "error": null}`
- **输出（失败）**：`{"ok": false, "data": null, "error": {"category": "system", "code": "POLICY_UNAVAILABLE", "message": "..."}}`
- **前置条件**：无。
- **错误**：
  - 输入非法：无（无输入）
  - 业务拒绝：无
  - 系统失败：规则源不可用 → `POLICY_UNAVAILABLE`（当前为本地常量，正常不会发生；保留以兼容未来改为配置/存储）
- **副作用**：无（只读）。
- **边界**：
  - 只读，不修改规则；
  - 返回最新版本；规则内容变化时版本号必须改变（`preview`/`submit` 的确认绑定依赖它）；
  - 规则是演示用，不代表真实商家政策或法律；
  - 本工具不给判定结论：最终能否退货由 `preview_return_request` / `validate_return_request` 判定，模型不得据此自行计算并跳过预览。
- **备注**：`summary` 用于向用户解释；`window_days` 等结构化字段只作展示与测试断言，不构成判定逻辑。

### preview_return_request

- **用途**：校验并生成退货申请方案（不写入）。
- **输入（模型可见）**：`order_line_id`（整数）、`quantity`（整数）。
- **注入（执行器）**：`current_user_id`（可信会话，模型不可指定）。
- **行为**：
  1. 用 `order_line_id` + 注入身份读取订单行；不存在或不属于当前身份 → 按业务拒绝 `FORBIDDEN`（不透露该行是否存在）。
  2. 调用 `validate_return_request(current_user_id, order_line, quantity)`。
  3. 允许 → 生成方案：`order_line_id`、`quantity`、`policy_version`、`plan_hash`。
     `plan_hash` = 对预览时刻的订单行快照做稳定序列化后取 SHA-256：
     `order_line_id|quantity|status|days_since_delivery|returnable|purchased_qty|reserved_qty`。
     不含 `policy_version`（版本另行比较）。
     预览与提交必须使用完全相同的字段顺序与序列化方式计算，否则哈希必然不等。
- **输出（允许）**：`{"ok": true, "data": {"allowed": true, "plan": {"order_line_id": 101, "quantity": 1, "policy_version": "policy-v1", "plan_hash": "<sha256>"}, "summary": "<给用户看的方案描述>"}, "error": null}`
- **输出（拒绝）**：`{"ok": false, "data": null, "error": {"category": "business", "code": "<reason_code>", "message": "<原因说明>"}}`
- **前置条件**：注入身份为 `strip()` 后非空的字符串；当前存在有效规则版本。
- **错误**：
  - 输入非法（`category=input`）：
    - 注入身份非法 → `INVALID_IDENTITY`
    - `order_line_id` 缺失或非整数 → `INVALID_ARGUMENT`

    其余输入合法性交给 `validate_return_request`。
  - 业务拒绝（`category=business`）：`validate_return_request` 返回的任何非 `OK` 原因码（`FORBIDDEN`/`NOT_DELIVERED`/`INVALID_INPUT`/`WINDOW_EXPIRED`/`ITEM_NOT_RETURNABLE`/`INVALID_QUANTITY`/`INSUFFICIENT_QUANTITY`）。
  - 系统失败（`category=system`）：`STORE_UNAVAILABLE`、`TIMEOUT`。
- **副作用**：无。不创建申请、不占用数量、不修改 `reserved_qty` 或任何业务数据。
- **边界**：
  - 不返回他人订单详情；
  - 不写入任何数据；
  - 方案必须绑定 `policy_version`；
  - 不生成确认——确认只能由 CLI 在用户显式输入「确认提交」后创建；
  - 不接受模型指定身份。
- **对执行器的要求**：本工具成功生成新方案时，执行器必须使当前待确认方案（若存在）失效，因为方案已被替换。
- **备注**：`INVALID_INPUT` 只作为 validate_return_request 的业务结论出现，不再用作参数错误码。

### submit_return_request

- **用途**：提交当前待确认的退货申请方案。
- **输入（模型可见）**：无。
- **注入（执行器）**：`current_user_id`；`confirmation`（当前待确认方案对象，含 `confirmation_id`、`user_id`、`plan`、`plan_hash`、`policy_version`、`created_at`、`expires_at`、`status`、`request_id`）。
- **行为**：
  1. 注入身份非法 → input / `INVALID_IDENTITY`
  2. 无 `confirmation` → business / `NO_PENDING_CONFIRMATION`
  3. `confirmation.user_id != current_user_id` → business / `CONFIRMATION_MISMATCH`
  4. `confirmation.status == used` → 返回 `already_exists` + 原 `request_id`（幂等，不再写库）
  5. `confirmation.status == invalid` → business / `CONFIRMATION_INVALID`
  6. `status == expired` 或 `now > expires_at` → business / `CONFIRMATION_EXPIRED`
  7. 读取当前订单行，用当前快照 + `confirmation.plan.quantity` 重算 `plan_hash`；与 `confirmation.plan_hash` 不一致 → 标记 `status = invalid`，返回 business / `PLAN_CHANGED`
  8. 当前 `policy_version` 与 `confirmation.policy_version` 不一致 → 标记 `status = invalid`，返回 business / `POLICY_CHANGED`
  9. 用第 7 步读取的同一份订单行，重新执行 `validate_return_request`；不通过 → 标记 `status = invalid`，返回 business / `<reason_code>`
  10. 同一事务内创建申请 + `reserved_qty += quantity`；成功后 `status = used`、记录 `request_id`
  11. 事务失败 → 回滚，system / `TRANSACTION_FAILED`
- **输出（成功）**：`{"ok": true, "data": {"request_id": "<id>", "status": "created", "order_line_id": 101, "quantity": 1}, "error": null}`
  （幂等重试时 `status` 为 `"already_exists"`，`request_id` 为原申请。）
- **输出（拒绝）**：`{"ok": false, "data": null, "error": {"category": "business", "code": "<code>", "message": "<说明>"}}`
- **前置条件**：存在有效确认，且 `confirmation.plan_hash` 与「按当前订单行快照 + `confirmation.plan.quantity` 重算的值」一致，且 `confirmation.policy_version` 与当前 `policy_version` 一致。
- **错误**：
  - 输入非法（`category=input`）：无模型可见参数；但注入身份非法 → `INVALID_IDENTITY`。
  - 业务拒绝（`category=business`）：`NO_PENDING_CONFIRMATION`、`CONFIRMATION_MISMATCH`、`CONFIRMATION_INVALID`、`CONFIRMATION_EXPIRED`、`PLAN_CHANGED`、`POLICY_CHANGED`，以及重新校验返回的 `reason_code`。
  - 系统失败（`category=system`）：`TIMEOUT`、`TRANSACTION_FAILED`。submit 是写路径，存储故障统一为 `TRANSACTION_FAILED`；`STORE_UNAVAILABLE` 仅用于只读工具。
- **副作用**：有。创建申请记录、增加 `reserved_qty`；必须同事务；失败无残留；同一确认重复提交只产生一条申请。
- **边界**：
  - 不接受模型自造的方案或确认；
  - 不修改订单归属、购买数量、商品属性和其他订单行；
  - 不跳过重新校验；
  - 不删除或改写已创建的申请记录。
