# 评测

## 内容

- `cases.py`：10 个固定案例与期望信号
- `checks.py`：判定逻辑（只看 trace 与数据库信号，不做文本打分）
- `run_eval.py`：运行器（`--baseline` 切换到固定流程）
- `baseline_fixed.py`：正则解析 + 直接调用工具的固定流程
- `pricing.json`：单价占位，未配置时只报告 token
- `results/`：每次运行的 JSON 结果（已提交）
- `runs/`：每次运行的 trace（已 gitignore）

## 运行

```bash
# Agent（会调用真实模型）
python3 -m eval.run_eval

# 只跑某个案例
python3 -m eval.run_eval --case C02

# 固定流程基线（不调用模型）
python3 -m eval.run_eval --baseline
```

每个案例使用独立临时数据库并写入同一份种子数据，互不影响。

## 判定信号

1. 必需工具是否出现、参数是否匹配
2. 工具返回的 `code` 是否出现
3. `submit` 是否被调用
4. 最终回复的关键词（contains / not_contains）
5. `return_requests` 新增条数

## 新增案例

在 `cases.py` 追加一项，字段：

```text
id, turns, required_tools, forbidden_tools, expected_codes,
preview_args, text_contains_any, text_not_contains, expect_new_requests
```

不要为了让某个实现通过而修改既有案例的期望值。