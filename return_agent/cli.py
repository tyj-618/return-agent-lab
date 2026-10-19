import os
import sys
import uuid
from datetime import datetime

from . import store
from .agent import Agent
from .llm import LLMClient, LLMError, load_env_file
from .trace import Tracer

DB_PATH = os.path.join("return_agent", "data", "demo.db")
RUNS_DIR = "runs"

# 演示身份：正式环境应由可信会话注入，不能由用户或模型指定。
DEMO_USER_ID = "U001"

EXIT_COMMANDS = {"exit", "quit", "退出"}


def main():
    load_env_file()
    try:
        llm = LLMClient()
    except LLMError as e:
        print(f"启动失败：{e}")
        return 1

    try:
        conn = store.connect(DB_PATH)
        store.init_schema(conn)
        store.seed_demo_data(conn)
    except store.StoreError as e:
        print(f"启动失败：{e}")
        return 1

    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    tracer = Tracer(os.path.join(RUNS_DIR, f"{run_id}.jsonl"))
    print(f"trace：{tracer.path}")
    print("输入 exit / quit / 退出 结束。")

    agent = Agent(llm, conn, DEMO_USER_ID, tracer)
    try:
        while True:
            user_message = input("你：").strip()
            if user_message in EXIT_COMMANDS:
                break
            if not user_message:
                continue
            result = agent.run(user_message)
            if result["text"]:
                print("助手：" + result["text"])
            if result["stop_reason"] != "final_answer":
                print(f"（本轮提前结束：{result['stop_reason']}）")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        tracer.close()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
