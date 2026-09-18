# -*- coding: utf-8 -*-
"""测试环境；真实群 ID 只从未提交到 Git 的 .env.test 读取。"""

import os

from config_prod import *


SESSION_NAME = os.environ.get("TG_SESSION_NAME", "ssc_offer_bot_test")

def _required_int(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"测试环境缺少 {name}，请从 TG应用 配置填入 .env.test")
    return int(value)


GROUP_HRBP = _required_int("TEST_GROUP_HRBP")
GROUP_LEADERSHIP = _required_int("TEST_GROUP_LEADERSHIP")
GROUP_RECRUIT = _required_int("TEST_GROUP_RECRUIT")
GROUP_REGULARIZATION_TRIGGER = _required_int("TEST_GROUP_TRIGGER")
GROUP_ANNIVERSARY_TRIGGER = GROUP_REGULARIZATION_TRIGGER

ANNIVERSARY_GROUP_RULES = [
    {"name": "测试-ACFAN", "keywords": ["ACFAN特战队", "ACFAN"], "chat_id": _required_int("TEST_GROUP_ANNIVERSARY_ACFAN")},
    {"name": "测试-运营一部", "keywords": ["运营一部", "运营1部"], "chat_id": _required_int("TEST_GROUP_ANNIVERSARY_OPS1")},
    {"name": "测试-运营二部", "keywords": ["运营二部", "运营2部"], "chat_id": _required_int("TEST_GROUP_ANNIVERSARY_OPS2")},
    {"name": "测试-渠道商务", "keywords": ["渠道部", "商务部", "渠道商务部"], "chat_id": _required_int("TEST_GROUP_ANNIVERSARY_CHANNEL")},
    {"name": "测试-技术效能", "keywords": ["技术部", "效能部", "技术效能部"], "chat_id": _required_int("TEST_GROUP_ANNIVERSARY_TECH")},
]

# 与生产实例共用收藏夹时，测试审批码必须带前缀，避免两套实例抢单。
OFFER_APPROVAL_CODE = "测试1"
REGULARIZATION_APPROVAL_CODE = "测试2"
ANNIVERSARY_APPROVAL_CODE = "测试3"
APPROVAL_CODES = frozenset({
    OFFER_APPROVAL_CODE, REGULARIZATION_APPROVAL_CODE, ANNIVERSARY_APPROVAL_CODE,
})
DAILY_REPORT_ENABLED = False
HRGS_FORWARD_ENABLED = False

REGULARIZATION_OUTPUT_FOLDER_ID = os.environ.get(
    "TEST_REGULARIZATION_OUTPUT_FOLDER_ID", REGULARIZATION_OUTPUT_FOLDER_ID
)
ANNIVERSARY_DRIVE_ROOT_ID = os.environ.get(
    "TEST_ANNIVERSARY_DRIVE_ROOT_ID", ANNIVERSARY_DRIVE_ROOT_ID
)

DB_PATH = "offer_state.test.json"
DAILY_REPORT_STATE_PATH = DB_PATH + ".daily_reports.json"
REGULARIZATION_STATE_PATH = DB_PATH + ".regularization.json"
ANNIVERSARY_STATE_PATH = DB_PATH + ".anniversary.json"
LOG_PATH = "bot.test.log"
