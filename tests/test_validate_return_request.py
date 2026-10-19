import copy
import unittest

from return_agent.validation import REASON_CODES, validate_return_request

BASE_USER = "U001"
BASE_QUANTITY = 1


def base_order_line(**overrides):
    line = {
        "order_id": 1001,
        "order_line_id": 101,
        "owner_id": "U001",
        "product_name": "蓝色 T 恤",
        "status": True,
        "days_since_delivery": 3,
        "purchased_qty": 2,
        "reserved_qty": 0,
        "returnable": True,
    }
    line.update(overrides)
    return line


# (用例 ID, current_user_id, order_line 差异, quantity, 预期 reason_code)
CASES = [
    # 调用身份输入
    ("T04", None, {}, BASE_QUANTITY, "INVALID_INPUT"),
    ("T05", "", {"owner_id": ""}, BASE_QUANTITY, "INVALID_INPUT"),
    ("T06", 1001, {}, BASE_QUANTITY, "INVALID_INPUT"),
    ("T38", " ", {"owner_id": " "}, BASE_QUANTITY, "INVALID_INPUT"),
    # 订单归属
    ("T01", BASE_USER, {"owner_id": "U002"}, BASE_QUANTITY, "FORBIDDEN"),
    ("T02", BASE_USER,
     {"owner_id": "U002", "status": False, "days_since_delivery": -1, "returnable": False},
     True, "FORBIDDEN"),
    ("T03", BASE_USER, {"owner_id": "u001"}, BASE_QUANTITY, "FORBIDDEN"),
    # 收货
    ("T08", BASE_USER, {"status": False}, BASE_QUANTITY, "NOT_DELIVERED"),
    ("T09", BASE_USER, {"status": False, "days_since_delivery": 20}, BASE_QUANTITY, "NOT_DELIVERED"),
    ("T35", BASE_USER, {"status": 1}, BASE_QUANTITY, "NOT_DELIVERED"),
    ("T37", BASE_USER, {"status": False, "days_since_delivery": -1}, BASE_QUANTITY, "NOT_DELIVERED"),
    # 期限
    ("T10", BASE_USER, {"days_since_delivery": 0}, BASE_QUANTITY, "OK"),
    ("T11", BASE_USER, {"days_since_delivery": 14}, BASE_QUANTITY, "OK"),
    ("T12", BASE_USER, {"days_since_delivery": 15}, BASE_QUANTITY, "WINDOW_EXPIRED"),
    ("T13", BASE_USER, {"days_since_delivery": -1}, BASE_QUANTITY, "INVALID_INPUT"),
    ("T14", BASE_USER, {"days_since_delivery": -1, "returnable": False}, BASE_QUANTITY, "INVALID_INPUT"),
    ("T15", BASE_USER, {"days_since_delivery": 15, "returnable": False}, BASE_QUANTITY, "WINDOW_EXPIRED"),
    # 可退属性
    ("T16", BASE_USER, {"returnable": False}, BASE_QUANTITY, "ITEM_NOT_RETURNABLE"),
    ("T17", BASE_USER, {"returnable": False}, 0, "ITEM_NOT_RETURNABLE"),
    ("T36", BASE_USER, {"returnable": 1}, BASE_QUANTITY, "ITEM_NOT_RETURNABLE"),
    # 数量格式
    ("T18", BASE_USER, {}, 0, "INVALID_QUANTITY"),
    ("T19", BASE_USER, {}, -1, "INVALID_QUANTITY"),
    ("T20", BASE_USER, {}, True, "INVALID_QUANTITY"),
    ("T21", BASE_USER, {}, False, "INVALID_QUANTITY"),
    ("T22", BASE_USER, {}, 1.0, "INVALID_QUANTITY"),
    ("T23", BASE_USER, {}, "1", "INVALID_QUANTITY"),
    ("T24", BASE_USER, {}, None, "INVALID_QUANTITY"),
    ("T25", BASE_USER, {"reserved_qty": 2}, True, "INVALID_QUANTITY"),
    # 数量余量
    ("T26", BASE_USER, {}, 1, "OK"),
    ("T27", BASE_USER, {}, 2, "OK"),
    ("T28", BASE_USER, {}, 3, "INSUFFICIENT_QUANTITY"),
    ("T29", BASE_USER, {"reserved_qty": 1}, 2, "INSUFFICIENT_QUANTITY"),
    ("T30", BASE_USER, {"reserved_qty": 1}, 1, "OK"),
    ("T31", BASE_USER, {"reserved_qty": 2}, 1, "INSUFFICIENT_QUANTITY"),
]

CASES_BY_ID = {case[0]: case for case in CASES}


def run_case(case_id):
    _, user_id, overrides, quantity, _ = CASES_BY_ID[case_id]
    line = base_order_line(**overrides)
    snapshot = copy.deepcopy(line)
    result = validate_return_request(user_id, line, quantity)
    return line, snapshot, result


class ValidateReturnRequestTest(unittest.TestCase):
    def test_reason_codes(self):
        for case_id, user_id, overrides, quantity, expected in CASES:
            with self.subTest(case_id):
                result = validate_return_request(user_id, base_order_line(**overrides), quantity)
                self.assertEqual(result, {"allowed": expected == "OK", "reason_code": expected})

    def test_t07_forbidden_result_has_no_other_order_details(self):
        _, _, result = run_case("T01")
        self.assertEqual(set(result), {"allowed", "reason_code"})
        self.assertEqual(result["reason_code"], "FORBIDDEN")
        self.assertIs(result["allowed"], False)

    def test_t32_allowed_path_does_not_mutate_order_line(self):
        line, snapshot, result = run_case("T26")
        self.assertEqual(result["reason_code"], "OK")
        self.assertEqual(line, snapshot)
        self.assertEqual(line["reserved_qty"], 0)

    def test_t33_rejected_paths_do_not_mutate_order_line(self):
        for case_id in ("T01", "T29"):
            with self.subTest(case_id):
                line, snapshot, _ = run_case(case_id)
                self.assertEqual(line, snapshot)

    def test_t34_result_contract_holds_for_all_cases(self):
        for case_id, *_ in CASES:
            with self.subTest(case_id):
                _, _, result = run_case(case_id)
                self.assertEqual(set(result), {"allowed", "reason_code"})
                self.assertIn(result["reason_code"], REASON_CODES)
                self.assertIs(result["allowed"], result["reason_code"] == "OK")


if __name__ == "__main__":
    unittest.main()
