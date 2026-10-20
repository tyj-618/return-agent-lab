# 缺陷台账

## 口径

- 证据只接受三类：commit 哈希、测试文件、`docs/dev-log.md` 的明确条目。
- 「谁发现」只取：我、Cursor 自查、测试、评测。依据是开发日志里的「发现的偏差 / 我的措施」，以及提交说明。对不上就写「待核实」。
- 「决策」：发现者已经归上、并且有明确修复的行写「我」；待核实行写「待核实」。
- 仓库里看不到缺陷前一版的，不把候选写成已发生的事实。

## 台账

| 编号 | 阶段 | 缺陷 | 谁发现 | 决策 | 后果 | 修复 | 预防 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | 契约 | 待核实。候选是「确认记录缺 user_id」。`1d223c6` 的 `docs/tools.md` 已要求 confirmation 含 `user_id`，日志没有缺字段的条目 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 |
| D02 | 实现 | 待核实。候选是「plan_hash 用确认自身字段重算，恒真」。`1d223c6` 起契约就是按当前订单行快照重算，仓库里没有恒真算法的提交 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 |
| D03 | 契约 | 待核实。候选是「身份非法在不同工具里分类不一致」。`1d223c6` 已写统一的 `INVALID_IDENTITY`，没有不一致的前一版 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 |
| D04 | 契约 | 待核实。候选是「INVALID_INPUT 同时归入两类」。`1d223c6` 的备注写「不再用作参数错误码」，但双分类的前一版不在仓库里 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 |
| D05 | 实现 | `2747d8c` 的 `query_orders` 把全部 `StoreError` 映射为 `STORE_UNAVAILABLE`，没有 `TIMEOUT`。契约 `1d223c6` 已经列出 `TIMEOUT` | 待核实 | 待核实 | 超时和存储故障返回同一个错误码 | `4b52416` 增加 `StoreTimeout`，工具层把超时映射为 `TIMEOUT` | `tests/test_store.py` 的 `test_real_lock_maps_to_store_timeout`；`tests/test_tools.py`、`tests/test_preview.py` 断言 `TIMEOUT` |
| D06 | 实现 | 待核实。候选是「按报错文字匹配，把 SQLITE_LOCKED 误判为超时」。`4b52416` 的 `docs/storage.md` 写了要避免这种误判，但仓库里没有宽泛匹配 `locked` 的前一版 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 |
| D08 | 实现 | 待核实。候选是「REJECTION_MESSAGES 下标取值会 KeyError」。`4b52416` 起就是 `.get(...)`，没有下标取值的提交 | 待核实 | 待核实 | 待核实 | 待核实 | 待核实 |
| D09 | 契约/实现 | 确认契约是嵌套 `plan`，存储是扁平列。证据：`docs/dev-log.md`「M2」发现的偏差第 1 条；`97dd3b8` | Cursor 自查 | 我 | 读出的确认形状和工具契约不一致 | `get_confirmation` 在边界组装嵌套 `plan`（`97dd3b8`） | `tests/test_store.py` 的 `test_confirmation_shape_matches_contract` |
| D10 | 存储 | `return_requests.confirmation_id` 只有 UNIQUE，没有外键。证据：同上第 2 条；`97dd3b8` 之前的 `schema.sql` 无 `REFERENCES`，该提交补上 | Cursor 自查 | 我 | 申请可以指向不存在的确认，UNIQUE 防不住 | `97dd3b8` 加上 `REFERENCES confirmations(confirmation_id)` | `tests/test_store.py` 的 `test_return_request_requires_existing_confirmation` |
| D11 | 存储 | `transaction()` 遇到连接上已有的隐式事务会失败。证据：同上第 3 条；`97dd3b8` 的 `conn.in_transaction` 检查 | Cursor 自查 | 我 | 调用方没提交上一段写入时，下一次事务直接报错 | 进入事务前若 `in_transaction` 则抛 `StoreError` | `tests/test_store.py` 的 `test_transaction_rejects_connection_already_in_transaction` |
| D12 | 存储 | `user_version=0` 且已有表的旧库会被当成新库并标成当前版本。证据：同上第 4 条；提交说明「schema 版本与旧库检测」（`97dd3b8`） | Cursor 自查 | 我 | 缺外键的旧文件不会被迁移，却得到当前版本号 | `user_version=0` 且已有业务表则拒绝初始化 | `tests/test_store.py` 的 `test_legacy_db_without_version_is_rejected` |
| D14 | 文档 | submit 的错误表写了 `STORE_UNAVAILABLE`，写路径实现不会返回它。证据：同上第 6 条；`97dd3b8` 写入该行，`1b5daaf` 删去 | 我 | 我 | 文档承诺的系统错误码和实现不一致 | `1b5daaf` 从 `docs/confirmation_flow.md` 和 `docs/tools.md` 去掉，写路径只留 `TIMEOUT` / `TRANSACTION_FAILED` | 同一提交的说明：`STORE_UNAVAILABLE` 只用于只读工具 |
| D15 | 评测 | C03/C04 首次评测要求出现 preview，Agent 实际走「查询后找不到」。证据：`af16df5` 的 `docs/evaluation.md` 第 5 节 | 评测 | 我 | 首次全量 6/10 里包含这两案的失败；查询后拒绝比越权预览更安全，期望本身不合适 | 用例改为只要求 `query_orders`（`eval/cases.py`，同提交） | 成功判定只看工具、错误码和新增申请，不把一条安全路径判失败 |
| D16 | 提示词 | C08/C09 模型不调用 preview，自行判断数量。证据：同上；第三次全量 C08 再次绕过 | 评测 | 我 | 最终句子可能对，但过程不合规；同一输入不稳定 | `af16df5` 在系统提示词和 preview 工具描述中要求数量合法性必须来自 preview，包括 0、负数和超量 | 评测看 `preview_return_request` 是否出现，不只看回复措辞 |
| D17 | 实现/文档 | 确认有效期 10 分钟散落在 8 处。证据：`docs/dev-log.md`「2026-10-20 · 改进」；`95fc435` 的父提交上，除该日志外有 8 个文件含 `10 分钟` / `minutes=10` / `10min` | 我 | 我 | 只改行为时，提示文案、测试和文档会各说各的 | `95fc435` 新增 `CONFIRMATION_TTL_MINUTES = 30`，行为、文案和测试改读常量 | 搜同一概念时覆盖 `10min`、`10 分钟`、`minutes=10`；历史日志不改 |
| D18 | 提示词 | 模型虚构「官方客服 / App 自助入口」。证据：`docs/dev-log.md`「M1′」发现的偏差第 1 条；`5fd34c2` | 我 | 我 | 回复提到当前系统没有的渠道 | 系统提示词增加「不要提及不存在的官方渠道、App 或客服」（`5fd34c2`） | 真实运行 trace 留在 `docs/traces/20261019-1625*.jsonl`，用来复查回复 |
| D19 | 提示词 | 输入「订单 1001」时，模型把 1001 读成「订单10」。证据：同上第 2 条；`5fd34c2` | 我 | 我 | 订单号被截断，可能对错行 | 提示词要求与工具返回的 `order_id` / `order_line_id` 精确匹配，不得截断、改写或补零 | 同一日志：连续 3 次运行的回复不再出现「订单10」 |
| D20 | 可观测 | trace 没有 user / assistant 事件，上面两条无法对照原文复盘。证据：同一条目的「我的措施」第 3 点；`5fd34c2` 的 `trace.py` | 我 | 我 | 只能看到工具调用，看不到用户原句和最终回复 | `Tracer.user_message` / `assistant_message`，文本截断至 2000 字符 | `docs/agent_flow.md` 列出这两类事件；`runs/` 不入库，放进 `docs/traces/` 前要人工检查 |

## 设计取舍

| 编号 | 取舍 | 选择 | 代价 | 记录位置 | 决策 |
| --- | --- | --- | --- | --- | --- |
| D07 | preview 注入 owner_id 以复用 validate | 归属只在存储层强制，不重复校验 | validate 的 FORBIDDEN 分支在预览路径不可达 | docs/storage.md 的不变式 | 我 |
| D13 | plan_hash 覆盖全部校验输入 | 状态变化先触发 PLAN_CHANGED | 重新校验成为防御性分支 | docs/confirmation_flow.md 第 3 节 | 我 |

## 统计

- 候选 20 条 = 缺陷 18 条（D01–D06、D08–D12、D14–D20）+ 设计取舍 2 条（D07、D13）。
- 缺陷中证据完整 11 条：D09–D12、D14–D20。
- 缺陷中待核实 7 条：D01–D06、D08（D05 缺陷已由 `2747d8c` 证实，仅发现者待核实）。
- 按发现者统计（含设计取舍，共 20 条）：
  - Cursor 自查 4 条：D09–D12
  - 我 7 条：D07、D13、D14、D17–D20
  - 评测 2 条：D15、D16
  - 待核实 7 条：D01–D06、D08
- 决策：我 13 条；待核实 7 条。
