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

## 表结构

见 `return_agent/schema.sql`。三张表：

- `order_lines`：订单行（业务事实）
- `return_requests`：退货申请记录
- `confirmations`：确认记录（M2 使用）

**不变量**：
- `purchased_qty > 0`
- `0 <= reserved_qty <= purchased_qty`
- `days_since_delivery >= 0`（负天数只在 `validate_return_request` 单测中覆盖，库中不允许出现）

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