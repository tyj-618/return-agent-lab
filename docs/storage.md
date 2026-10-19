# 存储设计（store）

## 决策记录（2026-10-19）

| 决策 | 结论 | 理由 |
| --- | --- | --- |
| 存储形态 | **SQLite（标准库 sqlite3）** | 真事务，可演示"提交失败无残留"与幂等；重启后数据仍在；不新增第三方依赖 |
| 库文件 | `return_agent/data/demo.db`，**不提交 git** | `.gitignore` 加 `*.db`、`return_agent/data/`；种子数据由代码插入 |
| 测试隔离 | `:memory:` + 统一 seed fixture | 每个测试独立，互不影响 |
| 商家表 | **不建** | 演示只服务一个虚构商家；该范围写在本文件，不引入无谓的表 |
| 申请记录表 | **现在就建**（M2 使用） | 避免 M2 改 schema 造成迁移 |
| 种子一致性 | `reserved_qty > 0` 的行必须同时插入对应申请记录 | 保证 `reserved_qty` 可由申请记录复算 |
| 返回形态 | `dict` | 字段与 `docs/tools.md` 的订单行一致，可直接序列化 |
| 读取身份 | `get_order_line(order_line_id, owner_id)` | 越权在存储层就查不到，多一层防线 |
| 错误表达 | 只读查不到返回 `None`；系统故障抛 `StoreError` | 由工具层映射为 `system` 错误 |
| 事务 | M2 用 `transaction()` 上下文管理器 | 保证"创建申请 + 增加 reserved_qty"原子 |
| 布尔转换 | SQLite 存 0/1，store 返回 dict 时转 `bool` | 与 `docs/tools.md`"工具边界负责转换"一致 |
| 时间格式 | ISO-8601 UTC 字符串 | 统一、可比较 |
| 确认表 | 现在就建（M2 使用） | 与申请记录同理 |
| 超时 | 按 SQLite 错误码 `SQLITE_BUSY` 识别（无错误码时精确匹配 "database is locked"），映射为 system/TIMEOUT | 避免把 SQLITE_LOCKED 等其他加锁错误误判为超时 |
| 归属校验 | 只在存储层强制（`get_order_line` 按 `owner_id` 过滤）；`preview` 不重复校验，注入 `owner_id` 仅用于复用 `validate_return_request` | 避免重复校验；代价是 `preview` 的 `FORBIDDEN` 分支不可达 |

## 表结构

见 `return_agent/schema.sql`。三张表：

- `order_lines`：订单行（业务事实）
- `return_requests`：退货申请记录
- `confirmations`：确认记录（M2 使用）

**不变量**：
- `purchased_qty > 0`
- `0 <= reserved_qty <= purchased_qty`
- `days_since_delivery >= 0`（负天数只在 `validate_return_request` 单测中覆盖，库中不允许出现）
- **`get_order_line` 必须始终按 `owner_id` 过滤**：`preview_return_request` 依赖这一点来保证归属；
  它注入 `owner_id` 只是为了复用 `validate_return_request`，`validate` 的 `FORBIDDEN` 分支在预览路径上不可达。
  若以后修改该查询，必须同步恢复 preview 的归属校验。

## 种子数据

当前用户 `U001`；另一测试用户 `U002`（用于越权用例）。

| order_id | order_line_id | owner | 商品 | status | days | purchased | reserved | returnable |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1001 | 101 | U001 | 蓝色 T 恤 | 1 | 3 | 2 | 0 | 1 |
| 1001 | 102 | U001 | 黑色卫衣 | 1 | 0 | 1 | 0 | 1 |
| 1002 | 201 | U001 | 运动鞋 | 0 | 5 | 1 | 0 | 1 |
| 1002 | 202 | U001 | 帆布包 | 1 | 15 | 1 | 0 | 1 |
| 1003 | 301 | U001 | 限量手办 | 1 | 2 | 1 | 0 | 0 |
| 1003 | 302 | U001 | 白色衬衫 | 1 | 7 | 2 | 1 | 1 |
| 1004 | 401 | U001 | 牛仔裤 | 1 | 14 | 2 | 2 | 1 |
| 1005 | 501 | U002 | 蓝色 T 恤 | 1 | 3 | 2 | 0 | 1 |

对应申请记录（保证可复算）：

| request_id | owner | order_line_id | quantity | policy_version | status |
| --- | --- | --- | --- | --- | --- |
| 9001 | U001 | 302 | 1 | policy-v1 | submitted |
| 9002 | U001 | 401 | 2 | policy-v1 | submitted |

`created_at` 用固定值 `2026-10-01T00:00:00Z`，`confirmation_id` 为 `NULL`。

## 接口

### M1（只读）

```text
connect(path=":memory:") -> sqlite3.Connection
init_schema(conn) -> None
seed_demo_data(conn) -> None                 # 幂等：INSERT OR IGNORE
list_order_lines(conn, owner_id) -> list[dict]
get_order_line(conn, order_line_id, owner_id) -> dict | None
```

### M2（写入）

```text
transaction(conn)                            # 上下文管理器：BEGIN IMMEDIATE / COMMIT / ROLLBACK
create_confirmation(conn, *, confirmation_id, user_id, order_line_id, quantity,
                    policy_version, plan_hash, created_at, expires_at) -> None
get_confirmation(conn, confirmation_id) -> dict | None
update_confirmation_status(conn, confirmation_id, status, request_id=None) -> None
create_return_request(conn, *, owner_id, order_line_id, quantity,
                      policy_version, confirmation_id, created_at) -> int   # 返回 request_id
get_return_request_by_confirmation(conn, confirmation_id) -> dict | None
increment_reserved(conn, order_line_id, quantity) -> None
```

- 写函数不自己开事务，由调用方用 `transaction()` 包裹；`transaction` 要求调用前连接**不在事务中**，否则抛 `StoreError`。块内异常回滚后原样抛出；`BEGIN` / `COMMIT` 的 `sqlite3.Error` 转为 `StoreError` / `StoreTimeout`。
- `get_confirmation` 返回契约形状（与 `docs/tools.md` 注入的 `confirmation` 一致）：顶层 `confirmation_id, user_id, plan, plan_hash, policy_version, created_at, expires_at, status, request_id`；`plan = {order_line_id, quantity, policy_version, plan_hash}`。`plan_hash` 与 `policy_version` 在顶层和 `plan` 内同值，来自同一行。
- `return_requests.confirmation_id` 有 `UNIQUE` 约束并外键引用 `confirmations(confirmation_id)`：同一确认只能产生一条申请，且不能引用不存在的确认。
- `update_confirmation_status`、`increment_reserved` 未更新到任何行时抛 `StoreError`；`increment_reserved` 超过 `purchased_qty` 时由 `CHECK` 约束拒绝，抛 `StoreError`。

## schema 版本与连接约束

- **版本号**：`store.SCHEMA_VERSION`（当前为 `1`）对应 SQLite 的 `PRAGMA user_version`。判定规则见下一小节。修改 `schema.sql` 时必须同步提升 `SCHEMA_VERSION`。

### schema 版本与旧库检测

`init_schema` 的判定规则：

1. `user_version == 0` 且库中没有任何业务表 → 新库，建表并写入 `SCHEMA_VERSION`；
2. `user_version == SCHEMA_VERSION` → 幂等，允许重复调用；
3. `user_version == 0` 但已存在业务表 → 旧库，拒绝并提示删除重建；
4. 其他版本号 → 版本不匹配，拒绝并提示删除重建。

库是演示数据，不做迁移。schema 变更后必须删除旧库：
`rm -f return_agent/data/*.db`。
- **外键是连接级设置**：`PRAGMA foreign_keys` 只对当前连接生效，不保存在库文件中。生产路径必须用 `store.connect` 建立连接（它会开启外键）；直接 `sqlite3.connect` 的连接不执行外键约束。
- **插入顺序**：`create_confirmation` → `create_return_request`（引用 `confirmation_id`）→ `update_confirmation_status` 回填 `request_id`。`confirmations` 与 `return_requests` 互相引用，必须按此顺序写入。
- **不删除申请记录**：本系统不删除 `return_requests` 中的记录。若未来需要删除，必须先解除引用（把 `confirmations.request_id` 置空）再删除。