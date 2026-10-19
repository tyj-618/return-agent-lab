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
  - `StoreError → system/STORE_UNAVAILABLE` 的工具层映射**尚未验证**（属 M1 第 4/5 步）；
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
- **用时 / 轮次 / 返工**：约【待你填】；1 轮。
- **局限与下次改进**：
  - `get_return_policy` 只断言了 version/window_days/summary，未断言其余规则字段（低风险，同源导入）；
  - `preview` 未实现（M1 第 5 步）；`submit` 未实现（M2）；
  - 工具尚未接入 Agent 循环，**模型可见 schema 尚未定义**。