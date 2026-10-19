# 确认与提交流程（M2）

## 1. 角色

| 谁 | 负责 |
| --- | --- |
| CLI | 精确匹配「确认提交」；调用内部 `create_confirmation`（**模型无权调用**） |
| 执行器（Agent） | 持有待确认方案；注入身份、连接、确认记录给工具 |
| 模型 | 可调用 `submit_return_request`（无参数），但不能创建确认 |
| 存储 | 事务内写申请 + 增加 `reserved_qty` + 更新确认状态 |

## 2. 状态机

```text
（无待确认方案）
   │ preview 成功（允许）
   ▼
pending_plan（执行器内存）
   │ 用户输入「确认提交」
   ▼
confirmation(status=pending, expires_at=now+10min,
             user_id, plan, plan_hash, policy_version)
   │ 模型调用 submit_return_request
   ▼
校验通过 → 事务写入 → confirmation.status=used, request_id=...
   │
   ▼
（清空 pending_plan）
```

## 3. 失效规则

| 事件 | 影响 |
| --- | --- |
| 新的 preview 成功 | 覆盖 `pending_plan`；若存在未使用的确认 → 标记 `invalid` |
| 用户取消 | 清空 `pending_plan`；未使用的确认 → `invalid` |
| 超过 `expires_at` | `submit` 时惰性判断 → `CONFIRMATION_EXPIRED` |
| 提交成功 | `used`，不可再用 |
| `plan_hash` 不匹配 | `invalid` + `PLAN_CHANGED` |
| `policy_version` 不匹配 | `invalid` + `POLICY_CHANGED` |
| 重新校验不通过 | `invalid` + 对应 `reason_code` |

由于 `plan_hash` 覆盖 `validate_return_request` 的全部输入，正常的订单状态变化会先得到 `PLAN_CHANGED`；重新校验是防御性检查，用于未来新增规则或哈希未覆盖的字段。

## 4. 幂等

- `return_requests.confirmation_id` 唯一约束：同一确认最多产生一条申请。
- `confirmation.status == used` → 直接返回 `already_exists` 与原 `request_id`，不再写库。
- 并发/重试由 `BEGIN IMMEDIATE` 串行化写事务。

## 5. 事务边界

一个事务内完成三件事：

1. 插入 `return_requests`；
2. `order_lines.reserved_qty += quantity`；
3. `confirmations.status = used, request_id = ...`

任一步失败 → 全部回滚，不得留下有效申请或数量占用。

submit 的全部检查与写入在同一事务内（BEGIN IMMEDIATE 提前取写锁），避免两个并发提交同时通过预检查。

## 6. 错误映射

| 情况 | category | code |
| --- | --- | --- |
| 注入身份非法 | input | `INVALID_IDENTITY` |
| 无确认 | business | `NO_PENDING_CONFIRMATION` |
| 确认不属于当前用户 | business | `CONFIRMATION_MISMATCH` |
| 确认已失效 | business | `CONFIRMATION_INVALID` |
| 确认已过期 | business | `CONFIRMATION_EXPIRED` |
| 方案快照变了 | business | `PLAN_CHANGED` |
| 规则版本变了 | business | `POLICY_CHANGED` |
| 重新校验不通过 | business | 对应 `reason_code` |
| 写库失败/超时 | system | `TRANSACTION_FAILED` / `TIMEOUT` |

submit 是写路径，存储故障统一归为 `TRANSACTION_FAILED`；`STORE_UNAVAILABLE` 只用于只读工具。

## 7. CLI 流程

1. 输入 `strip()` 后精确等于「确认提交」：
   - 无 `pending_plan` → 提示「当前没有可确认的方案」，不创建确认；
   - 有 → `create_confirmation()`，再交给 Agent 处理这条消息。
2. Agent 本轮若未调用 `submit_return_request` → 提示「未提交，确认将在 10 分钟后失效」。
3. 其他输入 → 正常对话。

## 8. 安全约束

- `create_confirmation` 不是模型工具，只能由 CLI 调用。
- 模型不能指定 `confirmation_id`；由执行器注入。
- 确认绑定 `plan_hash` + `policy_version`；任一变化即失效。
- 模型不能跳过 `submit` 用文字声称已提交。