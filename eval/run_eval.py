import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path

from return_agent import store
from return_agent.agent import Agent
from return_agent.llm import LLMClient, load_env_file
from return_agent.session import ChatSession
from return_agent.trace import Tracer

from eval.baseline_fixed import FixedFlow
from eval.cases import CASES
from eval.checks import check_case

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "eval" / "runs"
RESULTS_DIR = ROOT / "eval" / "results"
PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"
USER_ID = "U001"


def load_pricing():
    with PRICING_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def count_requests(conn):
    return conn.execute("SELECT COUNT(*) FROM return_requests").fetchone()[0]


def read_events(path):
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def summarize_trace(events):
    prompt = 0
    completion = 0
    latency_ms = 0
    tools = []
    for event in events:
        if event.get("type") == "model":
            prompt += event.get("prompt_tokens") or 0
            completion += event.get("completion_tokens") or 0
            latency_ms += event.get("duration_ms") or 0
        elif event.get("type") == "tool":
            tools.append(event.get("name"))
            latency_ms += event.get("duration_ms") or 0
    return {
        "prompt": prompt,
        "completion": completion,
        "total": prompt + completion,
        "latency_ms": latency_ms,
        "tools": tools,
    }


def cost_cny(pricing, prompt_tokens, completion_tokens):
    input_price = pricing.get("input_per_1m")
    output_price = pricing.get("output_per_1m")
    if input_price is None or output_price is None:
        return None
    return prompt_tokens / 1_000_000 * input_price + completion_tokens / 1_000_000 * output_price


def run_case(case, stamp, baseline=False):
    with tempfile.TemporaryDirectory() as tmp:
        conn = store.connect(str(Path(tmp) / "demo.db"))
        try:
            store.init_schema(conn)
            store.seed_demo_data(conn)
            before = count_requests(conn)
            texts = []
            trace_path = None
            if baseline:
                flow = FixedFlow(conn, USER_ID)
                events = []
                for turn in case["turns"]:
                    response = flow.handle(turn)
                    texts.append(response["text"] or "")
                    events = response["events"]
            else:
                trace_path = RUNS_DIR / f"{case['id']}-{stamp}.jsonl"
                tracer = Tracer(str(trace_path))
                try:
                    agent = Agent(LLMClient(), conn, USER_ID, tracer)
                    session = ChatSession(agent)
                    for turn in case["turns"]:
                        response = session.handle(turn)
                        texts.append(response["text"] or "")
                        if response["hint"]:
                            texts.append(response["hint"])
                finally:
                    tracer.close()
                events = read_events(trace_path)
            new_requests = count_requests(conn) - before
        finally:
            conn.close()
    passed, reasons = check_case(case, events, "\n".join(texts), new_requests)
    if baseline:
        usage = {"prompt": 0, "completion": 0, "total": 0, "latency_ms": 0, "tools": [
            event.get("name") for event in events if event.get("type") == "tool"
        ]}
    else:
        usage = summarize_trace(events)
    return {
        "id": case["id"],
        "passed": passed,
        "reasons": reasons,
        "tokens": {
            "prompt": usage["prompt"],
            "completion": usage["completion"],
            "total": usage["total"],
        },
        "latency_ms": usage["latency_ms"],
        "tools": usage["tools"],
        "texts": texts,
        "new_requests": new_requests,
        "trace": None if trace_path is None else str(trace_path),
    }


def print_report(results, pricing):
    print(f"{'case':<6} {'pass':<6} {'tokens':>8} {'latency_ms':>12}  tools  reasons")
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        tools = ",".join(result["tools"]) or "-"
        reasons = "; ".join(result["reasons"]) or "-"
        print(
            f"{result['id']:<6} {status:<6} {result['tokens']['total']:>8} "
            f"{result['latency_ms']:>12}  {tools}  {reasons}"
        )
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    prompt = sum(result["tokens"]["prompt"] for result in results)
    completion = sum(result["tokens"]["completion"] for result in results)
    latency = sum(result["latency_ms"] for result in results)
    print()
    print(f"通过率：{passed}/{total} ({passed / total:.0%})")
    print(f"平均 token：{(prompt + completion) / total:.1f}")
    print(f"平均延迟：{latency / total:.1f} ms")
    cost = cost_cny(pricing, prompt, completion)
    if cost is None:
        print(f"token 合计：输入 {prompt}，输出 {completion}（价格未配置，不算金额）")
    else:
        print(f"总成本：{cost:.6f} {pricing.get('currency') or ''}".rstrip())


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行退货 Agent 评测案例")
    parser.add_argument("--case", help="只跑一个案例，例如 C01")
    parser.add_argument("--baseline", action="store_true", help="跑固定流程基线，不调用模型")
    args = parser.parse_args(argv)
    cases = [case for case in CASES if args.case is None or case["id"] == args.case]
    if not cases:
        print(f"未知案例：{args.case}")
        return 1

    if not args.baseline:
        load_env_file()
    pricing = load_pricing()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    results = [run_case(case, stamp, baseline=args.baseline) for case in cases]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for result in results if result["passed"])
    prompt = sum(result["tokens"]["prompt"] for result in results)
    completion = sum(result["tokens"]["completion"] for result in results)
    report = {
        "stamp": stamp,
        "mode": "baseline" if args.baseline else "agent",
        "pricing": pricing,
        "results": results,
        "summary": {
            "passed": passed,
            "total": len(results),
            "pass_rate": passed / len(results),
            "avg_tokens": (prompt + completion) / len(results),
            "avg_latency_ms": sum(result["latency_ms"] for result in results) / len(results),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_cost": cost_cny(pricing, prompt, completion),
        },
    }
    name = f"{stamp}-baseline.json" if args.baseline else f"{stamp}.json"
    out = RESULTS_DIR / name
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_report(results, pricing)
    print(f"结果：{out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
