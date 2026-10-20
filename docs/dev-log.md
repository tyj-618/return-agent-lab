# 开发日志

## 2026-10-19 · M0：validate_return_request 从契约到可运行

- **任务与验收条件**
  - 按 `docs/tools.md` 的「内部校验函数」契约实现 `validate_return_request` 及其测试。
  - 契约要点：9 步判定顺序；身份非法 → `INVALID_INPUT`、owner 不匹配 → `FORBIDDEN`；
  `status`/`returnable` 用 `is True`；`quantity` 拒绝 `bool`；返回值只有 `allowed`、`reason_code`。
  - 验收：38 条用例（T01–T38）全部通过；实际运行输出可复现。
- **本次关注的链路环节**
  - 独立验证与纠偏（主线：实现后的审查 → 实际运行 → 定位归属）。
- **给 AI 的指令（摘要）**
  - 只实现 `validate_return_request` 与测试；必读 `docs/tools.md` 的契约与 `docs/data_model.md`；
  只改指定 3 个文件。
  - 不调用模型/联网/数据库；不许改契约或测试预期来迁就实现。
  - 要求先说明拟改文件，完成后给出实际运行输出。
- **我给了哪些上下文，为什么**
  - 两份：一份定义函数行为（判定顺序/错误码），一份定义字段类型与约束。
  - 没有把 `requirements` / `acceptance` 全文塞进去——本切片只需要契约，塞多了会冲淡约束。
- **AI 实际产出**
  - 新建 `return_agent/__init__.py`、`return_agent/validation.py`（50 行）、`tests/__init__.py`、
  `tests/test_validate_return_request.py`（36 条用例）。
  - 我审后要求补 `T37`、`T38`，并把第 1 步改为空白身份判 `INVALID_INPUT`。
- **我的判断：部分接受**
  - 接受：实现结构与 9 步判定顺序。
  - 拒绝："空白身份返回 `OK`"——裁定收紧为 `INVALID_INPUT`，并同步 `docs/tools.md`。
  - 补充：`T37` 锁住第 3/4 步的顺序。
  - 依据：权限函数里"静默接受异常身份"比"显式拒绝"危险；没有锁顺序的用例，顺序就是没被锁住。
- **发现的偏差**
  - **案例 A（验证方法问题，不是 AI 偏差）**：同一份测试，跑法不同结果不同。
    - 直接执行 `python3 tests/test_validate_return_request.py`
    → `ModuleNotFoundError: No module named 'return_agent'`
    - 四种跑法实测：A 直接跑文件 → 报错；B `python3 -m unittest discover -s tests -t .` → OK；
    C `python3 -m unittest discover -s tests` → OK；D `python3 -m tests.test_validate_return_request` → OK。
    - 根因：直接跑文件时 `sys.path[0]` 是脚本所在目录 `tests/`，不是项目根；用 `-m` 时 `sys.path[0]`
    是当前目录。
  - **案例 B（测试盲区）**：把第 3 步（`status`）与第 4 步（`days<0`）对调后，现有用例全部通过（全绿）。
    - 我第一次操作时把 `status` 移到了 `days>14` 之后（不是只与 `days<0` 交换），`T09` 变红：
    `WINDOW_EXPIRED != NOT_DELIVERED`。
    - 补 `T37` 后再对调第 3/4 步会变红：
      ```
      FAIL: test_reason_codes ... [T37]
      AssertionError: {'reason_code': 'INVALID_INPUT'} != {'reason_code': 'NOT_DELIVERED'}
      ```
- **我的措施**
  - 案例 A：在 `README.md` 写明必须用 `-m unittest` 的跑法，并说明不要直接执行测试文件。
  - 案例 B：补 `T37` 锁住顺序；按"对调 → 应全绿 → 补用例 → 应变红 → 还原 → 应全绿"验证。
  - 收紧空白身份：改 `validation.py` 第 1 步 + 同步 `docs/tools.md` + 加 `T38`。
- **独立验证**
  - 命令（**必须在项目根目录执行**）：
    ```
    python3 -m unittest discover -s tests -t .
    ```
  - 实际输出：
    ```
    ----------------------------------------------------------------------
    Ran 5 tests in 0.000s
    OK
    ```
  - 注意：输出里的 5 是「测试方法数」，不是用例数；用例是 38 条。
  - 定稿后补测的组合：`" "`/`" "` → `INVALID_INPUT`；删除 `owner_id` 键 → 抛 `KeyError`；
  `days=14` + `reserved_qty=1` + `quantity=2` → `INSUFFICIENT_QUANTITY`。
- **可辩护性门**
  - 代码通过测试后，闭卷回答三个设计问题 + 三个表外组合预测。
  - 首轮：3 题预测错 2；两问答"不知道"（`is True` 与真值判断的差别、删掉 `bool` 检查的后果）。
  其中"删掉 `isinstance(quantity, bool)`"暴露真实漏洞：`quantity=True` 会被当成 1，返回 `OK`。
  - 逐行走读 `validation.py` 九步与测试五个方法后重考：通过。
  - 结论：**代码正确 ≠ 我会了**。可辩护性门在成本最低处拦住了"AI 写、我讲不清"。
- **用时 / 轮次 / 返工**
  - 实际用时：日历约一周（中间补 Python 基础）；有效开发时间：【未知/估算】
  - 轮次：实现 1 轮 + 补充修订 1 轮（`T37`/`T38` + 收紧）。
  - 返工：一次顺序实验操作错误（`status` 移动过度），已还原。
- **局限与下次改进**
  - 本次跳过了"独立预期"（先自己写测试预期），测试预期可能锚定了 AI 给出的方案；
  下次至少对关键分支先写自己的预期再对照。
  - 首轮可辩护性门未通过，说明"代码能跑"和"我能解释"之间仍有距离；
  后续每个模块上简历前都要过这一门。
  - 实际用时未记录，无法评估返工成本；下次记录开始/结束时间。

## 2026-10-19 · M1：退货规则单一来源（policy.py）

- **任务与验收条件**：把窗口天数从 `validation.py` 的硬编码移到 `policy.py`，保证规则只有一处定义；
  验收：38 条用例仍通过，`WINDOW_DAYS` 只在 `policy.py` 定义。
- **本次关注的链路环节**：契约与实现的一致性 / 重构范围控制。
- **给 AI 的指令（摘要）**：只新建 `policy.py`、只改 `validation.py` 的常量来源；
  不动判定顺序、不动测试、不动文档；完成后跑测试并贴输出。
- **我给了哪些上下文，为什么**：只给"目标 + 两个文件 + 禁止项"。这是一次小重构，
  给整份契约反而会让它顺手改别的。
- **AI 实际产出**：新建 `policy.py`（`POLICY_VERSION`、`WINDOW_DAYS`、`REQUIRE_DELIVERED`、
  `REQUIRE_RETURNABLE`、`QUANTITY_RULE`、`SUMMARY`）；`validation.py` 顶部改为
  `from .policy import WINDOW_DAYS`，删除本地 `RETURN_WINDOW_DAYS`。
- **我的判断**：接受。依据：`WINDOW_DAYS` 只在 `policy.py` 定义，`validation.py` 只导入使用；
  判定顺序未变。
- **发现的偏差**：无。
- **我的措施**：无（不需要）。
- **独立验证**：
  - `grep -n "WINDOW_DAYS" return_agent/*.py`
    → `policy.py:2` 定义、`validation.py:1` 导入、`validation.py:39` 使用。
  - `python3 -m unittest discover -s tests -t .`
    → `Ran 5 tests in 0.000s` / `OK`
- **用时 / 轮次 / 返工**：约 1h；1 轮，无返工。
- **局限与下次改进**：本次只搬了窗口天数；`status`、`returnable`、数量规则仍写在校验代码里。
  若以后要做到"规则可配置"，需要把这几条也收进 `policy.py` 并由 `validate` 读取。
  当前演示范围不做。

## 2026-10-19 · M1：存储层（SQLite + 种子数据）

- **任务与验收条件**：按 docs/storage.md 实现 SQLite 存储与种子数据；
  验收：12 个测试通过、所有者过滤/排序/布尔转换/幂等/持久化均有断言。
- **本次关注的链路环节**：契约落地 / 数据结构设计 / 测试设计。
- **给 AI 的指令（摘要）**：给出 schema.sql 与接口签名；明确种子表、布尔转换、
  owner 过滤、StoreError 语义；只建 4 个文件；不实现 M2 的写接口。
- **我给了哪些上下文，为什么**：给完整 DDL 与种子表，不给实现代码——
  DDL 是契约，实现应留给 AI；同时避免它自创表结构。
- **AI 实际产出**：`return_agent/schema.sql`（三张表）、`return_agent/store.py`（112 行）、
  `tests/test_store.py`（7 个测试）、`docs/storage.md`。
- **我的判断**：接受。依据：DDL 单一来源、布尔转换在边界、owner 过滤在存储层、
  测试断言到字段集合与幂等计数，不是只测"能跑"。
- **发现的偏差**：无。
- **我的措施**：补了 StoreError 与文件库持久化两组测试（原实现只测 :memory:）。
- **独立验证**：
  - `python3 -m unittest discover -s tests -t .` → `Ran 12 tests ... OK`
  - 烟测 `data/demo.db` → `rows: 7`，`line 101` 的 status/returnable 为 True
- **用时 / 轮次 / 返工**：约 1h；1 轮实现 + 1 轮补测。
- **局限与下次改进**：
  - 已验证：`StoreError` 映射 `system/STORE_UNAVAILABLE`，`SQLITE_BUSY` 映射 `system/TIMEOUT`；
    真实锁用双连接 `BEGIN IMMEDIATE` + `timeout=0` 复现验证。
  - `create_return_request` / `increment_reserved` / `transaction` 尚未实现（M2）；
  - `connect` 建父目录只用已存在的临时目录测过，未单测嵌套路径。

## 2026-10-19 · M1：只读工具（query_orders / get_return_policy）

- **任务与验收条件**：按 docs/tools.md 实现两个只读工具；
  验收：19 个测试通过，含身份非法、存储故障、空结果、封装形状。
- **本次关注的链路环节**：契约落地 / 错误分层 / 边界测试设计。
- **给 AI 的指令（摘要）**：给出两个函数签名与返回结构；明确身份校验、
  `StoreError → system/STORE_UNAVAILABLE`、空结果不算业务拒绝；要求覆盖六组场景。
- **我给了哪些上下文，为什么**：只给 docs/tools.md 相关两节 + store 接口；
  不给实现代码，避免它照抄。
- **AI 实际产出**：`return_agent/tools.py`（48 行）、`tests/test_tools.py`（90 行，7 个测试）。
- **我的判断**：接受。依据：身份校验统一；`StoreError` 映射到 `system/STORE_UNAVAILABLE`；
  空结果返回 `ok=true, data=[]`；封装键集合有断言。
- **发现的偏差**：无。
- **我的措施**：无。
- **独立验证**：`python3 -m unittest discover -s tests -t .` → `Ran 19 tests ... OK`
- **用时 / 轮次 / 返工**：约 30min；1 轮。
- **局限与下次改进**：
  - `get_return_policy` 只断言了 version/window_days/summary，未断言其余规则字段（低风险，同源导入）；
  - `preview` 未实现（M1 第 5 步）；`submit` 未实现（M2）；
  - 工具尚未接入 Agent 循环，**模型可见 schema 尚未定义**。

## 2026-10-19 · M1：preview_return_request

- **任务与验收条件**：按 docs/tools.md 实现 preview（读订单行 → validate → 快照哈希 → 返回方案），
  不写入任何数据；验收：34 个测试通过，覆盖允许 / 业务拒绝 / 越权 / 不存在 / 输入非法 /
  系统失败 / 无副作用 / 哈希确定性 / 数量非法。
- **本次关注的链路环节**：契约落地 / 安全边界 / 测试设计。
- **给 AI 的指令（摘要）**：给出函数签名、判定顺序、`plan_hash` 的序列化方式、10 组测试要求，
  并明确"不得写入、不返回他人详情、policy_version 必须来自 policy.py"。
- **我给了哪些上下文，为什么**：只给 docs/tools.md 的 preview 一节 + store 接口 + validate 签名；
  不给实现代码，避免照抄。
- **AI 实际产出**：`return_agent/tools.py` 增加 `preview_return_request` 与 `compute_plan_hash`；
  `tests/test_preview.py`（12 个测试）。
- **我的判断**：接受，但有一处设计取舍需要记录（见"发现的偏差"）。
- **发现的偏差**：preview 为复用 `validate_return_request` 而注入 `owner_id=current_user_id`，
  导致 validate 的 `FORBIDDEN` 分支在预览路径不可达；归属实际只由存储层保证。
- **我的措施**：确认存储层确实按 owner 过滤（501 用例证明），并在 `docs/storage.md` 记录该隐性依赖
  与不变式，防止未来改动静默放行。
- **独立验证**：
  - `python3 -m unittest discover -s tests -t .` → `Ran 34 tests ... OK`
  - `test_plan_hash_changes_when_reserved_qty_changes` 通过 → 快照哈希能感知订单状态变化
- **用时 / 轮次 / 返工**：30min；1 轮实现 + 1 轮补测。
- **局限与下次改进**：
  - `submit` 与"新方案使旧确认失效"未实现（M2）；
  - 模型可见 schema 未定义（M1′）；
  - preview 不重复校验归属，依赖存储层过滤（已在 docs/storage.md 记录不变式）。

## 2026-10-19 · M1′：真实模型最小 Agent 循环（DeepSeek）

- **任务与验收条件**：接真实模型，跑通「澄清 → 预览 → 拒绝」闭环 + 可回放 trace；
  验收：51 个测试通过、4 类真实场景正常、trace 含 user/model/tool/assistant/stop。
- **本次关注的链路环节**：工具 schema 设计 / 上下文组织 / 真实运行验证。
- **给 AI 的指令（摘要）**：5 个决策（openai SDK、只暴露 3 工具、停止条件、系统提示词、JSONL trace）；
  循环测试用假 LLM、不联网。
- **我给了哪些上下文，为什么**：只给 docs/agent_flow.md 与工具契约；不给实现代码。
- **AI 实际产出**：`llm.py`、`agent.py`、`trace.py`、`tool_schemas.py`、`cli.py`，17 个循环测试。
- **我的判断**：接受；但发现两处问题并修正。
- **发现的偏差**：
  1. 模型虚构"官方客服 / App 自助入口"——违反"不能编造"；
  2. 输入"订单 1001"时，模型把 1001 读成"订单10"（模型侧解析错误）。
- **我的措施**：
  1. system prompt 增加"不要提及不存在的官方渠道、App 或客服"与"不确定就说明不确定"；
  2. 增加"订单号必须与工具返回的 order_id 精确匹配，不得截断改写"；
  3. trace 增加 user / assistant 事件（否则无法复盘上述问题）。
- **独立验证**：
  - `python3 -m unittest discover -s tests -t .` → `Ran 51 tests ... OK`
  - 同一输入连续 3 次运行，`docs/traces/20261019-1625*.jsonl`：
    3/3 用户输入含 1001、工具链为 query_orders → preview(101,1)、回复无"订单10"。
  - 正常流程 trace：`user → model → tool → model → tool → model → assistant → stop`。
  - 上下文 token 592 → 2307（未压缩，作为 M3 基线）。
- **用时 / 轮次 / 返工**：约【待你填】。
- **局限与下次改进**：
  - 3 次通过样本太小，未做更大规模复现；
  - 会话内订单数据不刷新（query_orders 一次调用后被历史复用）；
  - 上下文无压缩，token 随轮次增长；
  - `submit` 未实现（M2）。

## 2026-10-19 · M2：确认绑定 + submit + 幂等

- **任务与验收条件**：确认只能由 CLI 创建；模型调用 submit 时由执行器注入确认；
  提交前重校验快照/版本/规则；事务写入；重复提交幂等。
  验收：93 个测试通过 + 真实端到端提交一次。
- **本次关注的链路环节**：状态机设计 / 安全边界 / 事务与并发 / 真实运行。
- **给 AI 的指令（摘要）**：先设计文档再实现；拆成 M2a 存储写层与 M2b 接线；
  submit 全流程在 BEGIN IMMEDIATE 事务内；明确幂等与错误映射。
- **AI 实际产出**：store 写层 + transaction + schema 版本 + submit 工具 +
  Agent 的 pending_plan/confirmation + CLI 确认/取消 + 13 个新测试。
- **我的判断**：接受，但修正了 6 处设计问题（见下）。
- **发现的偏差与修正**：
  1. confirmation 契约是嵌套 plan，存储是扁平列 → get_confirmation 在边界组装契约形状；
  2. 只靠 UNIQUE 防重复 → 加 confirmation_id 外键；
  3. transaction 遇隐式事务会失败 → 显式检查 in_transaction 并报错；
  4. 旧库会被误标版本 → user_version=0 且已有表则拒绝；
  5. status 变化会先触发 PLAN_CHANGED → 文档写明重新校验是防御性分支；
  6. submit 的 STORE_UNAVAILABLE 实际不会返回 → 从错误表移除，统一 TRANSACTION_FAILED。
- **独立验证**：
  - `python3 -m unittest discover -s tests -t .` → `Ran 93 tests ... OK`
  - 真实端到端 trace `docs/traces/20261019-192522-83529d.jsonl`：
    `user → query_orders → preview(101,1) → assistant`，随后
    `user(确认提交) → submit → assistant`；
  - 库：return_requests 3 条（新增 9003），reserved_101=1，
    confirmation status=used、request_id=9003。
- **用时 / 轮次 / 返工**：约3h。
- **局限与下次改进**：
  - 并发测试只覆盖同进程两连接，未测多进程；
  - 确认 10 分钟过期只在单测验证，未做真实等待；
  - 会话内订单数据不刷新（query_orders 一次调用后被历史复用）。

### 2026-10-20 · 改进：确认有效期收敛为单一常量

- **触发**：现场改动题要求把确认有效期从 10 分钟改成 30 分钟。
- **问题**：同一个数字散落在 8 处——`agent.py` 的行为、`session.py` 的提示文案、
  3 个测试、2 份文档、基线实现；只改行为会导致文案和测试不一致。
- **决策**：新增 `return_agent/config.py` 的 `CONFIRMATION_TTL_MINUTES`；
  提示文案用 f-string 从常量派生；测试引用常量而不是硬编码。
- **改动**：`config.py`（新建）、`agent.py`、`session.py`、`baseline_fixed.py`、
  `test_confirm_flow.py`、`test_session.py`、`test_submit.py`、
  `docs/confirmation_flow.md`、`README.md`。
- **验证**：【跑完测试后填】；`grep` 复查后只剩 `docs/dev-log.md` 的历史记录。
- **可复用结论**：
  1. 凡"用户可见文案 + 测试断言 + 文档"都出现的数字，先收敛成常量再改；
  2. 搜同一概念要覆盖写法变体——这次 `10min` 就漏在"10 分钟 / minutes=10"之外；
  3. 历史日志（dev-log 自己）不算待改点，记录的是当时事实。