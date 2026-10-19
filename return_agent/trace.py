import json
import os
from datetime import datetime, timezone

MAX_TEXT_CHARS = 2000


class Tracer:
    """JSONL trace；run_id 取文件名（不含扩展名）。"""

    def __init__(self, path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.path = path
        self.run_id = os.path.splitext(os.path.basename(path))[0]
        self._file = open(path, "w", encoding="utf-8")

    def _write(self, step, type_, **fields):
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "step": step,
            "type": type_,
            **fields,
        }
        self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._file.flush()

    def model_call(self, step, model, usage, duration_ms, finish_reason):
        usage = usage or {}
        self._write(
            step, "model",
            model=model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            duration_ms=duration_ms,
            finish_reason=finish_reason,
        )

    def tool_call(self, step, name, args, status, category, code, duration_ms, result_summary):
        self._write(
            step, "tool",
            name=name,
            args=args,
            status=status,
            category=category,
            code=code,
            duration_ms=duration_ms,
            result_summary=result_summary,
        )

    def user_message(self, step, text):
        self._write(step, "user", text=(text or "")[:MAX_TEXT_CHARS])

    def assistant_message(self, step, text):
        self._write(step, "assistant", text=(text or "")[:MAX_TEXT_CHARS])

    def stop(self, step, reason, detail=None):
        self._write(step, "stop", reason=reason, detail=detail)

    def close(self):
        if not self._file.closed:
            self._file.close()
