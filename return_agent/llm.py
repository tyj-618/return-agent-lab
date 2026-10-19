import json
import os


class LLMError(Exception):
    pass


def load_env_file(path=".env"):
    """极简 KEY=VALUE 解析；已存在的环境变量不覆盖。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


class LLMClient:
    def __init__(self, model=None, base_url=None, api_key=None, timeout=30.0, max_retries=0):
        """重试由 Agent 在剩余时间预算内负责，客户端默认不重试。"""
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        model = model or os.environ.get("MODEL_NAME")
        base_url = base_url or os.environ.get("OPENAI_BASE_URL") or None
        missing = [
            name for name, value in (("OPENAI_API_KEY", api_key), ("MODEL_NAME", model))
            if not value
        ]
        if missing:
            raise LLMError(f"缺少环境变量：{', '.join(missing)}")

        try:
            import openai
        except ImportError as e:
            raise LLMError("未安装 openai，请先 pip install -r requirements.txt") from e

        self.model = model
        self._openai = openai
        self._client = openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries
        )

    def chat(self, messages, tools, timeout=None):
        kwargs = {"model": self.model, "messages": messages, "tools": tools}
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            response = self._client.chat.completions.create(**kwargs)
        except self._openai.OpenAIError as e:
            status = getattr(e, "status_code", None)
            detail = type(e).__name__ if status is None else f"{type(e).__name__} (HTTP {status})"
            raise LLMError(f"模型调用失败：{detail}") from e

        choice = response.choices[0]
        message = choice.message
        tool_calls = []
        for call in message.tool_calls or []:
            raw = call.function.arguments
            item = {"id": call.id, "name": call.function.name, "arguments_raw": raw}
            try:
                item["arguments"] = json.loads(raw or "{}")
            except (json.JSONDecodeError, TypeError):
                item["arguments"] = None
                item["parse_error"] = True
            tool_calls.append(item)

        usage = response.usage
        return {
            "text": message.content,
            "tool_calls": tool_calls,
            "finish_reason": choice.finish_reason,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
            },
        }
