IDENTITY_NOTE = "由执行器注入身份，不要请求用户身份。"

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_orders",
            "description": (
                "查询当前用户的全部订单行（含订单号、订单行号、商品名、收货状态、收货天数、"
                "购买数量、已占用数量）。在需要根据用户描述找到对应订单行、或核对订单信息时使用。"
                + IDENTITY_NOTE
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_return_policy",
            "description": (
                "读取退货规则及版本号。在需要向用户解释退货规则时使用；"
                "不能据此自行判断能否退货，判断必须调用 preview_return_request。"
                + IDENTITY_NOTE
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_return_request",
            "description": (
                "校验一次退货申请并生成方案，不会提交或写入。已确定订单行和退货数量后使用；"
                "判断能否退货必须调用本工具。" + IDENTITY_NOTE
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_line_id": {
                        "type": "integer",
                        "description": "订单行号，取自 query_orders 的结果",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "本次退货数量，正整数",
                    },
                },
                "required": ["order_line_id", "quantity"],
            },
        },
    },
]
