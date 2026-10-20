# 文档索引

## 建议阅读顺序

| 顺序 | 文件 | 内容 |
| --- | --- | --- |
| 1 | [requirements.md](requirements.md) | 目标、范围、不做什么 |
| 2 | [acceptance.md](acceptance.md) | E01–E03 验收场景 |
| 3 | [tools.md](tools.md) | 四个工具契约、统一封装、错误码分层 |
| 4 | [agent_flow.md](agent_flow.md) | Agent 循环、停止条件、trace、系统提示词 |
| 5 | [confirmation_flow.md](confirmation_flow.md) | 确认与提交状态机、事务边界、幂等 |
| 6 | [evaluation.md](evaluation.md) | 10 案例评测方法、结果、失败分析 |
| 7 | [dev-log.md](dev-log.md) | 每步的指令、判断、偏差与修正 |
| 8 | [defect-ledger.md](defect-ledger.md) | 已记录缺陷、修复与预防 |
| 9 | [ai-collaboration.md](ai-collaboration.md) | 协作链路、规则与实例 |
| 10 | [metrics.md](metrics.md) | 各里程碑的提交数、测试数与评测 |

## 按类别

| 类别 | 文件 | 说明 |
| --- | --- | --- |
| 需求 | [requirements.md](requirements.md) | 目标与范围 |
| 需求 | [data_model.md](data_model.md) | 订单行 / 申请 / 确认的字段 |
| 需求 | [acceptance.md](acceptance.md) | 验收案例与通过标准 |
| 契约 | [tools.md](tools.md) | 工具输入输出、错误码、确认绑定 |
| 契约 | [storage.md](storage.md) | 表结构、事务、schema 版本、不变式 |
| 设计 | [agent_flow.md](agent_flow.md) | 循环、澄清、异常分支、上下文、trace |
| 设计 | [confirmation_flow.md](confirmation_flow.md) | 确认创建、失效、幂等、安全约束 |
| 报告 | [evaluation.md](evaluation.md) | Agent 与基线的对比结果 |
| 日志 | [dev-log.md](dev-log.md) | 开发过程记录 |
| 过程 | [defect-ledger.md](defect-ledger.md) | 缺陷台账与证据 |
| 过程 | [ai-collaboration.md](ai-collaboration.md) | AI 协作方法与实例 |
| 过程 | [metrics.md](metrics.md) | 里程碑指标与口径 |
| 证据 | [traces/](traces/) | 真实运行的 JSONL trace |

## 维护约定

- 契约变更先改文档，再改代码。
- 文档与代码的 prompt 必须逐字一致（见 `agent_flow.md` §8）。
- 未验证的能力不写入文档，也不写入简历。