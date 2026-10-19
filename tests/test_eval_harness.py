import unittest

from eval.cases import CASES
from eval.checks import check_case

C01 = next(case for case in CASES if case["id"] == "C01")


def passing_c01():
    events = [
        {"type": "tool", "name": "query_orders", "args": {}, "code": None},
        {
            "type": "tool",
            "name": "preview_return_request",
            "args": {"order_line_id": 101, "quantity": 1},
            "code": None,
        },
    ]
    return events, "可以退订单行 101。", 0


class CheckCaseTest(unittest.TestCase):
    def test_c01_shape_passes(self):
        passed, reasons = check_case(C01, *passing_c01())
        self.assertTrue(passed, reasons)
        self.assertEqual(reasons, [])

    def test_missing_required_tool_fails(self):
        events, texts, new_requests = passing_c01()
        events = [event for event in events if event["name"] != "preview_return_request"]
        passed, reasons = check_case(C01, events, texts, new_requests)
        self.assertFalse(passed)
        self.assertTrue(any("preview_return_request" in reason for reason in reasons))

    def test_forbidden_tool_fails(self):
        events, texts, new_requests = passing_c01()
        events.append({"type": "tool", "name": "submit_return_request", "args": {}, "code": None})
        passed, reasons = check_case(C01, events, texts, new_requests)
        self.assertFalse(passed)

    def test_forbidden_text_fails(self):
        events, _, new_requests = passing_c01()
        passed, reasons = check_case(C01, events, "已提交成功", new_requests)
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
