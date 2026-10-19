# Agent 流程（M1′）

确认与提交流程见 docs/confirmation_flow.md。

## 1. 角色与边界

| 谁 | 负责 |
| --- | --- |
| Agent（模型） | 理解用户意图、判断是否澄清、选择工具、解释结果、给出方案 |
| 代码 | 注入身份与连接、校验工具入参、业务判定（`validate_return_request`）、计划哈希、循环上限、trace |

**模型不能做**：指定身份、跳过 `preview` 自行判断能否退货、未调用 `submit_return_request` 就声称已提交。

## 2. 模型可见工具（暴露 4 个）

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `query_orders` | `{}` | 查当前身份下的订单行 |
| `get_return_policy` | `{}` | 读取规则与版本号，用于解释 |
| `preview_return_request` | `{order_line_id: integer, quantity: integer}` | 校验并生成申请方案 |
| `submit_return_request` | `{}` | 提交当前已确认的方案；无参数，仅用户确认后可用 |

身份与数据库连接由执行器注入，不进入 schema。

## 3. 循环

状态：`messages`（system + 历史），跨用户消息保留。

每一轮：
1. 检查停止条件（轮数 / 工具数 / 超时）；
2. 调模型（带 tools）；
3. 若无 `tool_calls` → 输出最终答复，结束（`final_answer`）；
4. 若有 `tool_calls` → 逐个执行，把结果作为 tool 消息追加，回到第 1 步。

每批 `tool_calls` 必须全部得到结果消息（按 `tool_call_id` 一一对应），否则下一次模型调用的历史不合法。本次用户消息的工具预算（`MAX_TOOL_CALLS`）用尽时，同批剩余调用不执行，合成 `system / TOOL_BUDGET_EXCEEDED` 结果补齐，然后停止（`max_tool_calls`）。

`pending_plan` 与 confirmation 由执行器持有；新 preview 成功会使旧确认失效。

**停止原因**：`final_answer`、`max_turns`、`max_tool_calls`、`timeout`、`tool_errors`、`llm_error`。

## 4. 澄清

模型直接以文字提问即视为澄清；本轮以 `final_answer` 结束，等待用户下一条消息。**不需要专门的澄清工具**。

## 5. 异常分支

| 情况 | 处理 |
| --- | --- |
| 工具返回 `ok=false`（业务拒绝） | 原样作为 tool 结果回给模型，由模型解释 |
| 工具返回 `ok=false` 且 `category=system` | 计入"连续工具错误" |
| 工具名未知 / 参数解析失败 | 作为 tool 错误回给模型 |
| 连续 3 次工具错误 | 停止，`tool_errors` |
| 模型超时/网络错误 | 重试 2 次；仍失败 → `llm_error` |
| 单次用户消息超过 60 秒 | 停止，`timeout` |
| 执行器合成 `system / INVALID_TOOL_CALL`：工具名未知，或参数缺失 / 无法解析 | 作为 tool 结果回给模型；计入"连续工具错误"；计入已执行工具数 |
| 执行器合成 `system / TOOL_BUDGET_EXCEEDED`：工具预算用尽后同批剩余的调用 | 不执行，作为 tool 结果补齐后停止，`max_tool_calls`；不计入已执行工具数与"连续工具错误" |

**超时与重试**：每次模型调用前计算 `remaining = 60 - 已用时间`；`remaining <= 0` → 停止，`timeout`。单次调用超时 = `min(30, remaining)`。模型客户端 `max_retries=0`，不自行重试；由 Agent 在剩余时间预算内最多重试 2 次，重试用尽或预算耗尽 → `llm_error`。

## 6. 上下文

- system prompt 固定（见 §8）
- 对话历史：user / assistant / tool
- 工具结果只含当前用户数据；不引入长期记忆（M1′ 范围外）

## 7. Trace（JSONL）

- 路径：`runs/<run_id>.jsonl`（`runs/` 已加入 `.gitignore`）
- 一行一个事件，写完立即 flush
- `run_id` = 一次 CLI 会话（多轮用户消息共用）；`step` 在整个会话内全局递增

**事件类型**：

| type | 字段 |
| --- | --- |
| `user` | `ts, run_id, step, type, text`（用户输入，截断至 2000 字符） |
| `model` | `ts, run_id, step, type, model, prompt_tokens, completion_tokens, duration_ms, finish_reason` |
| `tool` | `ts, run_id, step, type, name, args, status, category, code, duration_ms, result_summary` |
| `assistant` | `ts, run_id, step, type, text`（最终回复，截断至 2000 字符） |
| `stop` | `ts, run_id, step, type, reason, detail` |

**隐私边界**：

- trace 可能包含**当前用户**的输入与助手回复原文（最长 2000 字符），视为敏感数据；
- **不记录 API Key**；
- **不记录他人订单详情**：工具只返回当前用户数据，trace 只记 `result_summary`，不记完整订单行；
- `runs/` 不入库；提交到 `docs/traces/` 作为证据前，**必须人工检查并剔除个人信息**。

## 8. System prompt（固定）

与 `return_agent/agent.py` 的 `SYSTEM_PROMPT` 逐字一致；修改任一处必须同步另一处。

你是退货申请助手，辅助用户进行退货。信息不足时要先澄清，不要猜。
不能自行判断是否能退货，必须调用 `preview_return_request`。
在 `submit` 未实现前，不能声称"已提交"，也不要承诺未来会开通提交功能。
当用户明确表示确认提交、且当前存在已确认的方案时，必须调用 submit_return_request；不得用文字代替工具调用，也不得在未调用工具的情况下声称已提交。
只能使用工具返回的事实，不能编造订单。
用户提到订单号或订单行号时，必须与工具返回的 order_id / order_line_id 精确匹配；不得截断、改写或补零。匹配不到就明确说没有找到，不要用其他订单替代。
不要提及不存在的官方渠道、App 或客服；只描述当前系统实际具备的能力。
不确定的信息直接说明不确定。
与用户交流使用中文，简洁明了。

## 9. M1′ 不做

UI、评测集、多轮记忆压缩。