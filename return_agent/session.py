from .config import CONFIRMATION_TTL_MINUTES


class ChatSession:
    """CLI 与评测共用的一轮输入处理。确认和取消不交给模型决定。"""

    def __init__(self, agent):
        self.agent = agent

    def handle(self, text):
        message = text.strip()
        if message == "确认提交":
            return self._confirm(message)
        if message == "取消":
            self.agent.cancel_pending()
            return {"text": "已取消，未提交任何退货申请。", "kind": "cancel", "hint": None}
        result = self.agent.run(message)
        return {"text": result["text"] or "", "kind": "chat", "hint": None}

    def _confirm(self, message):
        if not self.agent.pending_plan:
            return {
                "text": "当前没有可确认的方案，请先让我为你生成方案。",
                "kind": "confirm_blocked",
                "hint": None,
            }
        if self.agent.create_confirmation() is None:
            return {
                "text": "创建确认失败，请稍后重试。",
                "kind": "confirm_blocked",
                "hint": None,
            }
        result = self.agent.run(message)
        hint = None
        if "submit_return_request" not in result["tools_used"]:
            hint = f"（未提交，确认将在 {CONFIRMATION_TTL_MINUTES} 分钟后失效。）"
        return {"text": result["text"] or "", "kind": "confirm_created", "hint": hint}
