# return-agent-lab

退货申请处理 Agent（进行中）。

## 环境
Python 3.14（`python3 --version` 确认）。

## 运行测试
**必须在项目根目录执行：**

    python3 -m unittest discover -s tests -t .

⚠️ 不要用 `python3 tests/test_xxx.py` 直接跑：
直接执行文件时 Python 会把 `tests/` 而非项目根加入 sys.path，
导致 `ModuleNotFoundError: No module named 'return_agent'`。

## 目录
- `return_agent/` 业务代码
- `tests/` 测试
- `docs/` 需求、数据约定、验收案例、工具契约、开发日志
