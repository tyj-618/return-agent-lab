def _tool_events(events):
    return [event for event in events if event.get("type") == "tool"]


def check_case(case, events, texts, new_requests):
    """返回 (是否通过, 失败原因)。texts 是各轮助手文本拼在一起的字符串。"""
    reasons = []
    tools = _tool_events(events)
    names = [event.get("name") for event in tools]
    codes = [event.get("code") for event in tools]

    for name in case["required_tools"]:
        if name not in names:
            reasons.append(f"缺少必需工具：{name}")
    for name in case["forbidden_tools"]:
        if name in names:
            reasons.append(f"出现禁止工具：{name}")
    for code in case["expected_codes"]:
        if code not in codes:
            reasons.append(f"缺少错误码：{code}")

    preview_args = case["preview_args"]
    if preview_args is not None:
        matched = any(
            event.get("name") == "preview_return_request" and event.get("args") == preview_args
            for event in tools
        )
        if not matched:
            reasons.append(f"没有参数完全匹配的 preview：{preview_args}")

    needles = case["text_contains_any"]
    if needles and not any(needle in texts for needle in needles):
        reasons.append(f"回复未包含任一预期文本：{needles}")
    for phrase in case["text_not_contains"]:
        if phrase in texts:
            reasons.append(f"回复包含禁止文本：{phrase}")

    if new_requests != case["expect_new_requests"]:
        reasons.append(
            f"新增申请数不符：实际 {new_requests}，期望 {case['expect_new_requests']}"
        )
    return not reasons, reasons
