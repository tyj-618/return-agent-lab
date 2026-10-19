POLICY_VERSION = "policy-v1"
WINDOW_DAYS = 14
REQUIRE_DELIVERED = True
REQUIRE_RETURNABLE = True
QUANTITY_RULE = "quantity <= purchased_qty - reserved_qty"
SUMMARY = "已收货商品在收货后 0–14 个完整天内可申请退货；商品需支持退货；数量不超过剩余可退数量。"
