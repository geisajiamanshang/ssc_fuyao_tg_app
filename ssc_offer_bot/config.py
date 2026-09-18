# -*- coding: utf-8 -*-
"""按 BOT_ENV 加载测试或生产配置；未设置时保持现有生产行为。"""

import importlib
import os

from dotenv import load_dotenv


load_dotenv()

_environment = os.environ.get("BOT_ENV", "prod").strip().casefold()
if _environment not in {"test", "prod"}:
    raise RuntimeError("BOT_ENV 只能是 test 或 prod")
load_dotenv(os.path.join(os.path.dirname(__file__), f".env.{_environment}"))

_profile = importlib.import_module(f"config_{_environment}")
for _name in dir(_profile):
    if _name.isupper():
        globals()[_name] = getattr(_profile, _name)

# 新增的环境隔离开关集中在这里，为旧生产配置提供兼容默认值。
ENVIRONMENT = _environment
EXPECTED_SSC_USER_ID = int(os.environ.get("EXPECTED_SSC_USER_ID", "0"))
if ENVIRONMENT == "test" and not EXPECTED_SSC_USER_ID:
    raise RuntimeError("测试环境必须在 .env.test 设置 EXPECTED_SSC_USER_ID")
OFFER_APPROVAL_CODE = "测试1" if ENVIRONMENT == "test" else "1"
REGULARIZATION_APPROVAL_CODE = "测试2" if ENVIRONMENT == "test" else "2"
ANNIVERSARY_APPROVAL_CODE = "测试3" if ENVIRONMENT == "test" else "3"
APPROVAL_CODES = frozenset({
    OFFER_APPROVAL_CODE,
    REGULARIZATION_APPROVAL_CODE,
    ANNIVERSARY_APPROVAL_CODE,
})
DAILY_REPORT_ENABLED = ENVIRONMENT == "prod"
HRGS_FORWARD_ENABLED = ENVIRONMENT == "prod"
# 生产只接受指定机器人的提醒；测试群允许SSC人工粘贴提醒做联调。
ALLOW_MANUAL_TRIGGERS = ENVIRONMENT == "test"
ALLOWED_DESTINATION_IDS = frozenset({
    GROUP_LEADERSHIP,
    GROUP_RECRUIT,
    *(rule["chat_id"] for rule in ANNIVERSARY_GROUP_RULES),
})
